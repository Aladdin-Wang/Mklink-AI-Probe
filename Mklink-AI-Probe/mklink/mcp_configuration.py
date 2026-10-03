"""Offline configuration tools shared by MCP entry points; no device session."""


def register_configuration_offline_tools(mcp):
    @mcp.tool()
    def configuration_script(
        part_number: str, changes: dict[str, int], model: str = "V4"
    ) -> dict:
        """Generate a guarded STM32F103 USER/DATA/WRP offline script; no hardware writes. RDP is excluded."""
        from mklink.device_configuration import configuration_script as generate

        return generate(part_number, changes, model)

    @mcp.tool()
    def configuration_description(part_number: str, model: str = "V4") -> dict:
        """Describe supported option-byte/OTP fields without opening a device."""
        from mklink.device_configuration import describe_configuration

        return describe_configuration(part_number, model)
