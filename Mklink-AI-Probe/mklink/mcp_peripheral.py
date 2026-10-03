"""Offline installed peripheral descriptions shared by MCP entry points."""


def register_peripheral_offline_tools(mcp):
    @mcp.tool()
    def peripheral_targets(project_root: str = ".", query: str = "") -> dict:
        """List installed chip descriptions offline for an explicit local project.

        Does not connect or change a probe. For the connected backend's project
        use gui_call('peripheral_targets', {'q': query}).
        """
        from mklink.peripheral_watch import list_svd_targets

        return list_svd_targets(project_root, query)
