#!/usr/bin/env python3
import sys, json, urllib.request
q = sys.argv[1] if len(sys.argv)>1 else "test"
u = f"http://localhost:18000/query?q={urllib.parse.quote(q)}"
with urllib.request.urlopen(u) as r:
  data = json.loads(r.read().decode())
  assert data.get("citations"), "no citations in WS response"
  print("WS OK", data.get("provenance",{}).get("trace_id",""))
