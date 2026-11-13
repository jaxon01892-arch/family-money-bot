
from fastapi import FastAPI

app = FastAPI(title="Family Money")

@app.get("/")
async def home():
    return {
        "project": "Family Money",
        "status": "working",
        "message": "Оилавий молия тизими ишга тушди!"
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

