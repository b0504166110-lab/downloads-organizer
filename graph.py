"""
Builds the LangGraph graph from the nodes, and gives two functions to drive it:
start_run() - run until the graph stops for approval
resume_run() - continue with the user's answer

Run `python graph.py` for a terminal version of the whole flow (on the test folder by default).
"""

import time
import uuid
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

import config
import folders
import nodes
from state import GraphState


def build_graph():
    builder = StateGraph(GraphState)

    builder.add_node("scan_folder", nodes.scan_folder)
    builder.add_node("handle_duplicates", nodes.handle_duplicates)
    builder.add_node("classify_by_name", nodes.classify_by_name)
    builder.add_node("read_content", nodes.read_content)
    builder.add_node("classify_with_content", nodes.classify_with_content)
    builder.add_node("build_plan", nodes.build_plan)
    builder.add_node("human_review", nodes.human_review)
    builder.add_node("execute_actions", nodes.execute_actions)
    builder.add_node("report", nodes.report)

    # fixed edges
    builder.add_edge(START, "scan_folder")
    builder.add_edge("scan_folder", "handle_duplicates")
    builder.add_edge("handle_duplicates", "classify_by_name")
    builder.add_edge("read_content", "classify_with_content")
    builder.add_edge("classify_with_content", "build_plan")
    builder.add_edge("build_plan", "human_review")
    builder.add_edge("execute_actions", "report")
    builder.add_edge("report", END)

    # the BRANCH: unclear names -> read content
    builder.add_conditional_edges("classify_by_name", nodes.route_after_name,
                                  ["read_content", "build_plan"])
    # the LOOP: "read the content of X" goes back; approve goes on; cancel goes to the report
    builder.add_conditional_edges("human_review", nodes.route_after_review,
                                  ["read_content", "execute_actions", "report"])

    # The checkpointer saves the State after every node - this is what lets interrupt() pause and resume.
    return builder.compile(checkpointer=MemorySaver())


def _run_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "run_name": "downloads-organizer"}


def _run(graph, graph_input, thread_id: str, on_progress=None) -> dict:
    """
    Run the graph and report what happens, as events for on_progress:
      {"type": "start", "node": name}                       - a node started   (stream_mode "tasks")
      {"type": "end", "node": name, "seconds": s, "waiting": bool} - it finished / stopped at interrupt
      {"type": "progress", "text": ..., "done": i, "total": n}     - progress inside a node ("custom")
    Then read the saved state: stopped at the interrupt -> 'waiting', reached the end -> 'done'.
    """
    cfg = _run_config(thread_id)
    started: dict[str, float] = {}
    timings: list[tuple[str, float]] = []
    for mode, chunk in graph.stream(graph_input, cfg, stream_mode=["tasks", "custom"]):
        if mode == "custom":
            event = {"type": "progress", **chunk}
        elif "input" in chunk:  # a task started
            started[chunk["id"]] = time.perf_counter()
            event = {"type": "start", "node": chunk["name"]}
        else:                   # a task finished (or stopped at the interrupt)
            seconds = time.perf_counter() - started.pop(chunk["id"], time.perf_counter())
            timings.append((chunk["name"], seconds))
            event = {"type": "end", "node": chunk["name"], "seconds": seconds,
                     "waiting": bool(chunk.get("interrupts"))}
        if on_progress:
            on_progress(event)
    snapshot = graph.get_state(cfg)
    if snapshot.interrupts:
        payload = snapshot.interrupts[0].value
        return {"status": "waiting", "thread_id": thread_id, "timings": timings,
                "plan": payload["plan"], "existing_folders": payload["existing_folders"]}
    return {"status": "done", "thread_id": thread_id, "timings": timings,
            "report": snapshot.values.get("report", {})}


def graph_dot(graph, status: dict[str, tuple[str, float]]) -> str:
    """
    The graph as Graphviz DOT, colored by status: {node: ("done" | "running" | "waiting", seconds)}.
    Dashed edges are the conditional ones (the branch and the loop).
    """
    colors = {"done": "#C0DD97", "running": "#FAC775", "waiting": "#CECBF6"}
    g = graph.get_graph()
    lines = ['digraph G {', 'rankdir=TB; bgcolor="transparent";',
             'node [shape=box, style="rounded,filled", fontname="Arial", fontsize=11, fillcolor="#F1EFE8", color="#B4B2A9"];',
             'edge [color="#888780"];']
    for node_id in g.nodes:
        if node_id in ("__start__", "__end__"):
            lines.append(f'"{node_id}" [label="{node_id.strip("_")}", shape=oval, fontsize=9];')
            continue
        state, seconds = status.get(node_id, ("pending", 0.0))
        label = node_id
        if state == "done":
            label += f"\\n✓ {seconds:.1f}s"
        elif state == "running":
            label += "\\n... עובד"
        elif state == "waiting":
            label += "\\nמחכה לאישור"
        fill = colors.get(state, "#F1EFE8")
        width = "2.5" if state == "running" else "1"
        lines.append(f'"{node_id}" [label="{label}", fillcolor="{fill}", penwidth={width}];')
    for e in g.edges:
        style = "dashed" if e.conditional else "solid"
        lines.append(f'"{e.source}" -> "{e.target}" [style={style}];')
    lines.append("}")
    return "\n".join(lines)


def start_run(graph, source_dir: str | None = None, dest_root: str | None = None,
              thread_id: str | None = None, on_progress=None, folder_list: list[dict] | None = None) -> dict:
    """Run from the start until the graph stops for approval (or finishes).
    folder_list: [{name, description}] - the user's folders; None = the saved list (folders.json) or the default."""
    thread_id = thread_id or str(uuid.uuid4())
    initial = {"source_dir": str(source_dir or config.SOURCE_DIR),
               "dest_root": str(dest_root or config.DEST_ROOT),
               "folder_list": folder_list if folder_list is not None else folders.load_folders()}
    return _run(graph, initial, thread_id, on_progress)


def resume_run(graph, thread_id: str, answer: dict, on_progress=None) -> dict:
    """Continue a paused run with the user's answer (see nodes.human_review for its shape)."""
    return _run(graph, Command(resume=answer), thread_id, on_progress)


def save_graph_images(graph, folder: Path = config.PROJECT_DIR) -> list[str]:
    """Save the graph as Mermaid text (always works) and as PNG (needs mermaid.ink online)."""
    saved = []
    g = graph.get_graph()
    (folder / "graph.mmd").write_text(g.draw_mermaid(), encoding="utf-8")
    saved.append("graph.mmd")
    try:
        (folder / "graph.png").write_bytes(g.draw_mermaid_png())
        saved.append("graph.png")
    except Exception as e:
        print(f"PNG not created ({type(e).__name__}) - graph.mmd is enough for GitHub.")
    return saved


# =====================================================================
# Terminal version (the test of step 5)
# =====================================================================

def _print_plan(plan: list[dict]) -> None:
    print()
    for i, item in enumerate(plan, start=1):
        flags = []
        if item["is_new_folder"]:
            flags.append("NEW FOLDER")
        if item["used_content"]:
            flags.append("by content")
        if item["excluded"]:
            flags.append("EXCLUDED")
        if item.get("new_name"):
            flags.append(f"RENAME -> {item['new_name']}")
        print(f"{i:3}. {item['file'][:45]:45} -> {item['folder']:15} conf={item['confidence']:.2f} {' '.join(flags)}")


def _ask_user(plan: list[dict]) -> dict:
    print("\nCommands:  a = approve   c = cancel   r 3 7 = read content of items 3 and 7   x 5 = exclude item 5")
    excluded = [i["file"] for i in plan if i["excluded"]]
    while True:
        parts = input("> ").strip().split()
        if not parts:
            continue
        cmd, nums = parts[0].lower(), parts[1:]
        try:
            picked = [plan[int(n) - 1]["file"] for n in nums]
        except (ValueError, IndexError):
            print("Unknown item number.")
            continue
        if cmd == "a":
            return {"action": "approve", "excluded": excluded}
        if cmd == "c":
            return {"action": "cancel"}
        if cmd == "r" and picked:
            return {"action": "approve", "excluded": excluded, "read_content": picked}
        if cmd == "x" and picked:
            excluded += picked
            print("Excluded:", ", ".join(picked))
            continue
        print("Unknown command.")


def main() -> None:
    issues = config.check_config()
    if issues:
        raise SystemExit("Setup problems:\n - " + "\n - ".join(issues))
    if config.SOURCE_DIR.resolve() != (config.SANDBOX_DIR / "downloads").resolve():
        print(f"WARNING: this is NOT the test folder: {config.SOURCE_DIR}")
        if input("Type YES to continue: ") != "YES":
            raise SystemExit("Stopped.")

    graph = build_graph()
    print("Graph image:", ", ".join(save_graph_images(graph)))
    print(f"Organizing {config.SOURCE_DIR} -> {config.DEST_ROOT}")

    def show(event: dict) -> None:
        if event["type"] == "progress":
            print("  ", event["text"])
        elif event["type"] == "end":
            print(f"[{event['node']}] {event['seconds']:.1f}s" + (" (waiting for approval)" if event["waiting"] else ""))

    result = start_run(graph, on_progress=show)
    while result["status"] == "waiting":
        _print_plan(result["plan"])
        result = resume_run(graph, result["thread_id"], _ask_user(result["plan"]), on_progress=show)

    r = result["report"]
    print("\n=== Report ===")
    print("Cancelled" if r.get("cancelled") else f"Moved: {len(r['moved'])}")
    print(f"Renamed: {sum(1 for f, _folder, final in r['moved'] if final != f)}")
    print(f"Duplicates sent to Recycle Bin: {len(r['duplicates_trashed'])}")
    print(f"Excluded (left in Downloads): {len(r['excluded'])}")
    print(f"Skipped: {len(r['skipped'])}")
    for f, why in r["blocked"]:
        print(f"BLOCKED: {f} - {why}")


if __name__ == "__main__":
    main()
