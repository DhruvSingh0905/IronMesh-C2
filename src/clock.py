import json

class VectorClock:
    def __init__(self, node_id, clock_state=None):
        self.node_id = node_id
        self.clock = clock_state if clock_state else {}
        if self.node_id not in self.clock:
            self.clock[self.node_id] = 0

    def increment(self):
        """Event happens locally -> increment our own counter"""
        self.clock[self.node_id] = self.clock.get(self.node_id, 0) + 1
        return self.clock.copy()

    def merge(self, other_clock_dict):
        """
        Sync with another node. 
        Rule: Take the MAX of every node's counter.
        """
        all_nodes = set(self.clock.keys()) | set(other_clock_dict.keys())
        for node in all_nodes:
            self.clock[node] = max(
                self.clock.get(node, 0),
                other_clock_dict.get(node, 0)
            )

    def to_dict(self):
        return self.clock.copy()

    @staticmethod
    def compare(clock_a, clock_b):
        """
        Compare two clock dicts.
        Returns:
        -1 if A < B (A happened before B)
         1 if A > B (A happened after B)
         0 if Concurrent (Conflict / Partition)
        """
        keys = set(clock_a.keys()) | set(clock_b.keys())
        a_greater = False
        b_greater = False

        for k in keys:
            val_a = clock_a.get(k, 0)
            val_b = clock_b.get(k, 0)
            
            if val_a > val_b: a_greater = True
            if val_b > val_a: b_greater = True

        if a_greater and not b_greater: return 1  
        if b_greater and not a_greater: return -1 
        return 0 