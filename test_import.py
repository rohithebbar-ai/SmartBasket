import sys
print("Python:", sys.version, flush=True)
print("Path:", sys.executable, flush=True)

print("Testing asyncpg...", flush=True)
import asyncpg
print("asyncpg OK", flush=True)

print("Testing dotenv...", flush=True)
from dotenv import load_dotenv
print("dotenv OK", flush=True)

print("All imports OK", flush=True)
