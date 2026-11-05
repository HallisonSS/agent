from pydantic import BaseModel
from typing import Literal
import ipaddress

class Plan(BaseModel):
    action: Literal["none","ban","deny","unban"]
    ip: str | None = None
    reason: str
    risk: Literal["low","medium","high"]

def validate(plan: Plan):
    if plan.action != "none":
        ipaddress.ip_address(plan.ip)   # levanta erro se inválido
