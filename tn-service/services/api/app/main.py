from fastapi import FastAPI
app = FastAPI(title="TN Service API")
@app.get("/health")
def health():
    return {"status": "ok"}
