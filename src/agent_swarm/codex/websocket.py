"""WebSocket messages over the native daemon proxy's byte streams."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from websockets.client import ClientProtocol
from websockets.frames import Frame, Opcode
from websockets.http11 import Response
from websockets.protocol import OPEN
from websockets.uri import parse_uri


class CodexWebSocket:
    """Let websockets own Upgrade, masking and protocol control frames."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Wrap the proxy pipes without creating a service or selecting a socket."""
        self._reader = reader
        self._writer = writer
        self._connection = ClientProtocol(
            parse_uri('ws://localhost/rpc'), max_size=128 * 1024 * 1024,
        )
        self._events = self._read_events()

    async def _flush(self) -> None:
        """Write protocol output, including automatic Ping and Close replies."""
        for data in self._connection.data_to_send():
            if data:
                self._writer.write(data)
        await self._writer.drain()

    async def open(self) -> None:
        """Use the native client's localhost/rpc Upgrade over the proxy pipes."""
        self._connection.send_request(self._connection.connect())
        await self._flush()
        event = await anext(self._events)
        if not isinstance(event, Response) or self._connection.state is not OPEN:
            raise ValueError(f'Codex WebSocket Upgrade rejected: {event}')

    async def send(self, message: str) -> None:
        """Send one JSON-RPC document as a WebSocket Text message."""
        self._connection.send_text(message.encode('utf-8'))
        await self._flush()

    async def _read_events(self) -> AsyncIterator[Response | Frame]:
        """Keep all decoded events, including coalesced handshake and data."""
        while True:
            data = await self._reader.read(65536)
            if data:
                self._connection.receive_data(data)
            else:
                self._connection.receive_eof()
            await self._flush()
            for event in self._connection.events_received():
                yield event
            if not data:
                return

    async def messages(self) -> AsyncIterator[str]:
        """Reassemble Text messages while the library handles protocol controls."""
        fragments: list[bytes] = []
        async for event in self._events:
            if not isinstance(event, Frame):
                raise ValueError(f'Unexpected Codex WebSocket event: {event}')
            if event.opcode in (Opcode.TEXT, Opcode.CONT):
                fragments.append(event.data)
                if event.fin:
                    yield b''.join(fragments).decode('utf-8')
                    fragments.clear()
            elif event.opcode is Opcode.CLOSE:
                return
            elif event.opcode not in (Opcode.PING, Opcode.PONG):
                raise ValueError(f'Unexpected Codex WebSocket frame: {event.opcode}')
