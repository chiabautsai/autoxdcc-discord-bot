# weechat_relay_client.py (Using the correct 'input' command)
import asyncio
import struct
import config

class WeeChatRelayClient:
    def __init__(self):
        self.host = config.WEECHAT_RELAY_HOST
        self.port = config.WEECHAT_RELAY_PORT
        self.password = config.WEECHAT_RELAY_PASSWORD
        self.reader = None
        self.writer = None

    async def _connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

    async def _send(self, command: str):
        self.writer.write(command.encode('utf-8') + b'\n')
        await self.writer.drain()

    async def _receive(self) -> str:
        header = await self.reader.readexactly(4)
        total_length = struct.unpack('!I', header)[0]
        bytes_to_read = total_length - 4
        raw_data = await self.reader.readexactly(bytes_to_read)
        compression_type = raw_data[0]
        message_data = raw_data[1:]
        if compression_type != 0x00:
             raise NotImplementedError("Compression is not supported.")
        return message_data.decode('utf-8', 'ignore').strip()

    def _close(self):
        if self.writer and not self.writer.is_closing():
            self.writer.close()

    async def _perform_full_login(self):
        if not self.password:
            raise ValueError("WeeChat relay password is not set.")
        await self._connect()
        await self._send("handshake")
        await self._receive()
        await self._send(f"init password={self.password}")

    async def run_command_with_response(self, command: str) -> str:
        try:
            await self._perform_full_login()
            await self._send(f"(resp_cmd) {command}")
            response = await self._receive()
            return response
        finally:
            self._close()

    async def run_fire_and_forget_command(self, command: str):
        try:
            await self._perform_full_login()
            full_relay_command = f"input core.weechat {command}"
            await self._send(f"(ff_cmd) {full_relay_command}")
            # The 'input' command does not send a response, so we do not wait.
        finally:
            self._close()
