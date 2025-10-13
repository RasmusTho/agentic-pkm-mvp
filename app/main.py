import os
if os.getenv("DEBUGPY") == "1":
    import debugpy
    port = int(os.getenv("DEBUGPY_PORT", "5678"))
    debugpy.listen(("0.0.0.0", port))
    print(f"debugpy listening on 0.0.0.0:{port}")
    if os.getenv("DEBUGPY_WAIT") == "1":
        print("Waiting for debugger attach...")
        debugpy.wait_for_client()

from fastapi import FastAPI
app = FastAPI()


@app.get("/")
def root():
    return {"ok": True, "service": "api"}


