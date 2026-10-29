"""Run the user's unmodified smem with four scanner processes on this large host."""
import multiprocessing
from pathlib import Path
import runpy

if __name__ == "__main__":
    multiprocessing.cpu_count = lambda: 4
    runpy.run_path(str(Path(__file__).with_name("smem")), run_name="__main__")
