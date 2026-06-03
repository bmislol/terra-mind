from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class EchoRequest(BaseModel):
    message: str
    hp: int


class EchoResponse(BaseModel):
    reply: str


@app.post("/echo", response_model=EchoResponse)
async def echo(body: EchoRequest) -> EchoResponse:
    return EchoResponse(reply=f"Echo: {body.message} (HP={body.hp})")
