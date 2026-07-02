import json
import os
import math
from datetime import datetime

TREE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace", "deep_think_tree.json")

def load_tree():
    if not os.path.exists(TREE_FILE):
        return None
    with open(TREE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tree(tree_data):
    os.makedirs(os.path.dirname(TREE_FILE), exist_ok=True)
    with open(TREE_FILE, "w", encoding="utf-8") as f:
        json.dump(tree_data, f, indent=2, ensure_ascii=False)

def init_tree(problem_description):
    tree = {
        "problem": problem_description,
        "nodes": {
            "root": {
                "id": "root",
                "parent": None,
                "visits": 1,
                "value": 0.0,
                "conjecture": "Base problem, no hypothesis yet.",
                "code": "",
                "status": "EVALUATED",
                "result_log": "",
                "children": []
            }
        }
    }
    save_tree(tree)
    print(f"Tree initialized for problem: {problem_description}")

def _calculate_uct(node_id, tree):
    node = tree["nodes"][node_id]
    if node["visits"] == 0:
        return float('inf')
    
    parent = tree["nodes"][node["parent"]] if node["parent"] else None
    parent_visits = parent["visits"] if parent else 1
    
    exploitation = node["value"] / node["visits"]
    exploration = math.sqrt(2 * math.log(parent_visits) / node["visits"])
    
    return exploitation + exploration

def get_best_leaf():
    tree = load_tree()
    if not tree:
        print("Tree not found. Initialize first.")
        return None
        
    nodes = tree["nodes"]
    
    # We want a node that is EVALUATED but has either 0 children (leaf) 
    # or we want to traverse using UCT to find a node to expand.
    
    def traverse(current_id):
        node = nodes[current_id]
        if not node["children"]:
            return current_id
        
        # If there are unexplored children, pick one
        unexplored = [c for c in node["children"] if nodes[c]["visits"] == 0]
        if unexplored:
            return unexplored[0]
            
        # Otherwise use UCT
        best_child = max(node["children"], key=lambda c: _calculate_uct(c, tree))
        return traverse(best_child)

    best_id = traverse("root")
    return nodes[best_id]

def add_node(parent_id, conjecture, code):
    tree = load_tree()
    import uuid
    new_id = f"node_{uuid.uuid4().hex[:8]}"
    
    new_node = {
        "id": new_id,
        "parent": parent_id,
        "visits": 0,
        "value": 0.0,
        "conjecture": conjecture,
        "code": code,
        "status": "PENDING",
        "result_log": "",
        "children": []
    }
    
    tree["nodes"][new_id] = new_node
    tree["nodes"][parent_id]["children"].append(new_id)
    save_tree(tree)
    print(f"Added node {new_id} to parent {parent_id}")
    return new_id

def update_node(node_id, result_log, reward):
    tree = load_tree()
    node = tree["nodes"][node_id]
    
    node["status"] = "EVALUATED"
    node["result_log"] = result_log
    
    # Backpropagate
    current_id = node_id
    while current_id:
        curr = tree["nodes"][current_id]
        curr["visits"] += 1
        curr["value"] += reward
        current_id = curr["parent"]
        
    save_tree(tree)
    print(f"Node {node_id} evaluated with reward {reward}. Tree backpropagated.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "init" and len(sys.argv) > 2:
            init_tree(sys.argv[2])
        elif cmd == "best":
            best = get_best_leaf()
            if best:
                print(f"Best node to expand: {best['id']}")
                print(f"Conjecture: {best['conjecture']}")
                print(f"Code: {best['code']}")
        elif cmd == "add" and len(sys.argv) > 4:
            print(add_node(sys.argv[2], sys.argv[3], sys.argv[4]))
        elif cmd == "update" and len(sys.argv) > 4:
            update_node(sys.argv[2], sys.argv[3], float(sys.argv[4]))
        else:
            print("Usage: python deep_think_mcts.py [init <problem> | best | add <parent> <conj> <code> | update <id> <log> <reward>]")
