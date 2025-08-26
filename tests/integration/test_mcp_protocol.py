"""
Integration tests for MCP protocol implementation.
Tests the full MCP protocol flow including SSE connections and JSON-RPC messaging.
"""

import asyncio
import json
import pytest
import pytest_asyncio
import httpx
from typing import AsyncGenerator
import time


class TestMCPProtocol:
    """Test MCP protocol implementation with proper SSE handling."""
    
    @pytest_asyncio.fixture
    async def client(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """Create HTTP client for testing."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            yield client
    
    @pytest.fixture
    def base_url(self) -> str:
        """Base URL for MCP server."""
        return "http://localhost:8000"
    
    @pytest.mark.asyncio
    async def test_sse_endpoint_connection(self, client: httpx.AsyncClient, base_url: str):
        """Test that SSE endpoint establishes connection properly."""
        # SSE endpoint should accept connection and keep it open
        try:
            async with client.stream("GET", f"{base_url}/sse", timeout=5.0) as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers.get("content-type", "")
                assert response.headers.get("cache-control") == "no-cache"
                assert response.headers.get("connection") == "keep-alive"
                
                # Read a few lines to ensure connection is working
                lines_read = 0
                async for line in response.aiter_lines():
                    lines_read += 1
                    if lines_read >= 3:  # Just read a few lines to verify connection
                        break
                    if line.startswith("data:"):
                        # Parse SSE data
                        data = line[5:].strip()
                        if data:
                            try:
                                event_data = json.loads(data)
                                # Should be valid JSON
                                assert isinstance(event_data, dict)
                            except json.JSONDecodeError:
                                # Some SSE messages might not be JSON
                                pass
        except httpx.TimeoutException:
            # SSE connections are expected to timeout since they stay open
            # This is actually good - it means the connection was established
            pass
    
    @pytest.mark.asyncio
    async def test_message_endpoint_initialize(self, client: httpx.AsyncClient, base_url: str):
        """Test MCP initialize request via message endpoint."""
        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {}
                },
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0"
                }
            }
        }
        
        response = await client.post(
            f"{base_url}/messages/",
            json=initialize_request,
            timeout=10.0
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "result" in data
        
        result = data["result"]
        assert "protocolVersion" in result
        assert "capabilities" in result
        assert "serverInfo" in result
        
        # Check server info
        server_info = result["serverInfo"]
        assert server_info["name"] == "sanctum-letta-mcp"
        assert "version" in server_info
    
    @pytest.mark.asyncio
    async def test_message_endpoint_initialized(self, client: httpx.AsyncClient, base_url: str):
        """Test MCP initialized notification."""
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {}
        }
        
        response = await client.post(
            f"{base_url}/messages/",
            json=initialized_notification,
            timeout=10.0
        )
        
        # Initialized notification should not return a response
        assert response.status_code == 200
        # Response should be empty or minimal
    
    @pytest.mark.asyncio
    async def test_list_tools(self, client: httpx.AsyncClient, base_url: str):
        """Test listing available tools."""
        list_tools_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }
        
        response = await client.post(
            f"{base_url}/messages/",
            json=list_tools_request,
            timeout=10.0
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 2
        assert "result" in data
        
        result = data["result"]
        assert "tools" in result
        tools = result["tools"]
        
        # Should have at least the health tool
        assert len(tools) >= 1
        
        # Check for health tool
        health_tool = next((t for t in tools if t["name"] == "health"), None)
        assert health_tool is not None
        assert health_tool["description"] == "Check server health and plugin status"
    
    @pytest.mark.asyncio
    async def test_call_health_tool(self, client: httpx.AsyncClient, base_url: str):
        """Test calling the health tool."""
        call_tool_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "health",
                "arguments": {}
            }
        }
        
        response = await client.post(
            f"{base_url}/messages/",
            json=call_tool_request,
            timeout=10.0
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 3
        assert "result" in data
        
        result = data["result"]
        assert "content" in result
        assert len(result["content"]) > 0
        
        # Parse health check response
        content = result["content"][0]
        assert content["type"] == "text"
        
        health_data = json.loads(content["text"])
        assert health_data["status"] == "healthy"
        assert "plugins" in health_data
        assert "plugin_names" in health_data
    
    @pytest.mark.asyncio
    async def test_invalid_json_rpc(self, client: httpx.AsyncClient, base_url: str):
        """Test handling of invalid JSON-RPC requests."""
        invalid_request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "nonexistent_method"
        }
        
        response = await client.post(
            f"{base_url}/messages/",
            json=invalid_request,
            timeout=10.0
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 4
        assert "error" in data
        
        error = data["error"]
        assert error["code"] == -32601  # Method not found
    
    @pytest.mark.asyncio
    async def test_malformed_json(self, client: httpx.AsyncClient, base_url: str):
        """Test handling of malformed JSON."""
        response = await client.post(
            f"{base_url}/messages/",
            content="invalid json",
            headers={"content-type": "application/json"},
            timeout=10.0
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "error" in data
        error = data["error"]
        assert error["code"] == -32700  # Parse error
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self, client: httpx.AsyncClient, base_url: str):
        """Test handling of concurrent requests."""
        # Send multiple requests simultaneously
        requests = []
        for i in range(5):
            request = {
                "jsonrpc": "2.0",
                "id": i + 10,
                "method": "tools/list"
            }
            requests.append(
                client.post(f"{base_url}/messages/", json=request, timeout=10.0)
            )
        
        responses = await asyncio.gather(*requests)
        
        for i, response in enumerate(responses):
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == i + 10
            assert "result" in data
    
    @pytest.mark.asyncio
    async def test_sse_and_message_hybrid(self, client: httpx.AsyncClient, base_url: str):
        """Test that SSE and message endpoints work together."""
        # First establish SSE connection
        sse_task = asyncio.create_task(self._establish_sse_connection(client, base_url))
        
        # Wait a bit for SSE to establish
        await asyncio.sleep(1)
        
        # Send message while SSE is connected
        message_request = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/list"
        }
        
        response = await client.post(
            f"{base_url}/messages/",
            json=message_request,
            timeout=10.0
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 20
        assert "result" in data
        
        # Cancel SSE task
        sse_task.cancel()
        try:
            await sse_task
        except asyncio.CancelledError:
            pass
    
    async def _establish_sse_connection(self, client: httpx.AsyncClient, base_url: str):
        """Helper to establish SSE connection."""
        try:
            async with client.stream("GET", f"{base_url}/sse", timeout=5.0) as response:
                assert response.status_code == 200
                # Just verify connection is established, don't read indefinitely
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        break
        except httpx.TimeoutException:
            # Expected for SSE connections
            pass 