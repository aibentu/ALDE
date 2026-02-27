import subprocess
from openai import OpenAI
import os
from PySide6.QtWidgets import QApplication

from pathlib import Path
from dotenv import load_dotenv


def _try_chathistory_log(event: str, *, data: dict | None = None) -> None:
    try:
        try:
            from .chat_completion import ChatHistory  # type: ignore
        except Exception:
            from alde.chat_completion import ChatHistory  # type: ignore
        ChatHistory().log(
            _role="tool",
            _content=event,
            _obj="model",
            _data=data or {},
            _thread_name="model",
            _name_tool="openai.chat.completions.create",
        )
    except Exception:
        return

# how the message object have to looks like
"""
input=[
        {
            "role": "developer",
            "content": "Talk like a pirate."
        },
        {
            "role": "user",
            "content": "Are semicolons optional in JavaScript?"
        }
    ]
"""

def _read_api_key() -> str:
            __root_env = Path(
                __file__).resolve(
                ).parents[1] / ".env"
            __local_env = Path(
                __file__).with_suffix(".env"
                )

            for f in (__root_env, __local_env):
                if f.exists():
                    load_dotenv(
                        f, override=False
                        )
                    break

            load_dotenv()                     # fallback
            __key = os.getenv("OPENAI_API_KEY")
            if not __key:
                raise RuntimeError(
                    "OPENAI_API_KEY not found – supply it via .env or environment."
                )
            return __key

class ChatComEditor():
    _api_key = _read_api_key
    messages: list = []
    def __init__(self, 
            _api_key,
            path:str|list|None, 
            file:str|list|None,
            _input_text:str,
            editor:str = None
                ):

            super().__init__()

            self.instruction = (
                 """ You are an expert DevOps assistant. 
                 Du generierst sicheren, getesteten und ausfürlich dokumentierten 
                 Production ready Code für Python GUI's entwickeld mit Qt6-PySide6. 
                 Du bist verantwortlich für das writing, debugging und refactoring.
                 Jede Antwort muss: 
                 (1) kompilierten/ready to run Code oder 
                 (2) dropin patches, ein oder mehrteilig, liefern. 
                 (3) betroffener, fehlerhafter Code muss neu geschrieben werden. 
                 (4) eine Kurz­erklärung liefern 
                 """
                )
            
            self.system_message = (
                )

            self.path = path 
            self.file = file 
            self.input_text = _input_text
            self.editor = editor
            self.model = "o3-2025-04-16"  #"gpt-5-chat-latest" 
            self.client = OpenAI(api_key=_read_api_key())
            self.messages = [
                {
                "role" : "user", "content" : self.input_text
                },
                {
                "role" : "developer", "content" : self.instruction
                },
                {
                "role" : "system", "content" : self.system_message
                }
        ]
            

    def _response(self):
            _try_chathistory_log(
                "openai.chat.completions.create request",
                data={"model": self.model, "n_messages": len(self.messages)},
            )
            try:
                self.response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                )
            except Exception as exc:
                _try_chathistory_log(
                    "openai.chat.completions.create error",
                    data={"model": self.model, "error": f"{type(exc).__name__}: {exc}"},
                )
                raise
            _try_chathistory_log(
                "openai.chat.completions.create response",
                data={"model": self.model, "response_id": getattr(self.response, "id", None)},
            )
            return self.response.choices[0].message.content

    def _editor(self,e):
            e=e
            return subprocess.run(
                ({self.editor}), 
            shell = False
                )
            
    def _readit(self):
           print(f'{self.path}{self.file}')
           for file in {self.file}:
               with open(f'{self.path}{file}', "r") as f:
                   return f.read()

    def _writeit(self,w):
            w=w
            with open(f"{self.path}{self.file[:]}", "a") as file:
                print(self.file[:0])
                print(f"Writing to {self.path}{self.file}")
                print(f"{w}")
                return file.write(f"{w}")        


if __name__ == "__main__":  

    # Example usage - this is test/example code
    # Use relative path from this file's location for actual usage
    orpath = str(Path(__file__).resolve().parent)
    path = os.path.join(orpath)
    file:list|str = "vector_smanager.py"
    _api_key = ""
    editor= "gnome-text-edit"

    _input_text = ChatComEditor(_api_key,  path, file,  _input_text="" )._readit() + (
           """ [ERROR] 'Document' object is not subscriptable
 """
)
    chatcom_t = ChatComEditor("", path, file,
         _input_text=_input_text
         )
    w = chatcom_t._response()

    chatcom = ChatComEditor(_api_key, path, file,
       _input_text = None
    )
    chatcom._writeit('\n\n\n'f" '''{w}''' ")        









