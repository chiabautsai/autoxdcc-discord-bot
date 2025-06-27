import asyncio
import struct
import config

class WeeChatRelayClient:
    """
    A robust, asynchronous client for the WeeChat relay protocol.
    It correctly handles the one-way nature of 'init' and 'input' commands
    and performs a graceful shutdown.
    """
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

    async def _close(self):
        """Gracefully closes the connection by sending 'quit'."""
        if self.writer and not self.writer.is_closing():
            try:
                # The 'quit' command is the polite way to disconnect.
                await self._send("quit")
            except Exception:
                # Ignore errors if the socket is already dead.
                pass
            finally:
                self.writer.close()
            
    async def _perform_full_login(self):
        if not self.password:
            raise ValueError("WeeChat relay password is not set.")
        await self._connect()
        
        # 1. Handshake (sends a response)
        await self._send("handshake")
        await self._receive()
        
        # 2. Authenticate (is silent, does not send a response)
        await self._send(f"init password={self.password}")

    async def run_fire_and_forget_command(self, command: str):
        """
        Connects, authenticates, sends a one-way command, and gracefully disconnects.
        """
        try:
            await self._perform_full_login()
            
            # Send the main command (is silent, does not send a response)
            full_relay_command = f"input core.weechat {command}"
            await self._send(f"(cmd) {full_relay_command}")
            
        finally:
            # Always ensure we disconnect gracefully.
            await self._close()
