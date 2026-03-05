from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str
