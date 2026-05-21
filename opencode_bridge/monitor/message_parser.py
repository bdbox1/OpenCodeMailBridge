from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedMessage:
    raw: str
    sender: str
    matched: bool
    command: str = ""


class MessageParser:
    def __init__(self, contact_name: str, command_prefix: str):
        self.contact_name = contact_name
        self.command_prefix = command_prefix

    def parse(self, sender: str, content: str) -> ParsedMessage:
        result = ParsedMessage(raw=content, sender=sender, matched=False)
        if sender != self.contact_name:
            return result
        stripped = content.strip()
        if not stripped.startswith(self.command_prefix):
            return result
        command = stripped[len(self.command_prefix):].strip()
        if not command:
            return result
        result.matched = True
        result.command = command
        return result
