"""AI Content Optimizer offline extraction cascade.

Core logic uses pure functions (html to harvest to gate to markdown). Vertex
model client and storage access sit behind interfaces allowing offline and cloud execution.
"""

__version__ = "0.0.1"
