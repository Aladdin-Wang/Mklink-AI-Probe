use serde::{Deserialize, Serialize};
use std::fs;
use std::net::IpAddr;
use std::path::{Path, PathBuf};

const CONFIG_SCHEMA: &str = "mklink.site-agent.config.v1";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SiteAgentConfig {
    pub schema: String,
    pub enabled: bool,
    pub transport: String,
    pub bind_host: String,
    pub port: u16,
    pub allow_lan: bool,
    #[serde(default)]
    pub stcp_server_addr: String,
    #[serde(default = "default_stcp_server_port")]
    pub stcp_server_port: u16,
    #[serde(default)]
    pub stcp_user: String,
    #[serde(default)]
    pub stcp_proxy_name: String,
}

fn default_stcp_server_port() -> u16 {
    7000
}

impl Default for SiteAgentConfig {
    fn default() -> Self {
        Self {
            schema: CONFIG_SCHEMA.into(),
            enabled: false,
            transport: "direct".into(),
            bind_host: "127.0.0.1".into(),
            port: 8766,
            allow_lan: false,
            stcp_server_addr: String::new(),
            stcp_server_port: default_stcp_server_port(),
            stcp_user: String::new(),
            stcp_proxy_name: String::new(),
        }
    }
}

impl SiteAgentConfig {
    pub fn validate(
        &self,
        token_configured: bool,
        stcp_credentials_configured: bool,
    ) -> Result<(), String> {
        if self.schema != CONFIG_SCHEMA {
            return Err("Unsupported Site Agent configuration schema".into());
        }
        if self.transport != "direct" && self.transport != "lan-stcp" {
            return Err("Transport must be direct or lan-stcp".into());
        }
        if self.bind_host.trim() != self.bind_host || self.bind_host.is_empty() {
            return Err("The Site Agent bind address is invalid".into());
        }
        let address: IpAddr = self
            .bind_host
            .parse()
            .map_err(|_| "The Site Agent bind address must be a local IP address".to_string())?;
        if address.is_unspecified() || address.is_multicast() {
            return Err("Wildcard, unspecified, and multicast listeners are forbidden".into());
        }
        if self.port == 0 {
            return Err("The Site Agent port must be in 1..65535".into());
        }
        if !self.enabled {
            return Ok(());
        }
        if !token_configured {
            return Err("Generate a Site Agent access token before enabling the service".into());
        }
        if self.transport == "direct" {
            if !address.is_loopback() && !self.allow_lan {
                return Err("A LAN/VPN listener requires explicit LAN access".into());
            }
            return Ok(());
        }
        if !address.is_loopback() || self.allow_lan {
            return Err("LAN STCP requires a loopback Site Agent listener".into());
        }
        if !stcp_credentials_configured {
            return Err("LAN STCP credentials are not configured".into());
        }
        if self.stcp_server_addr.trim() != self.stcp_server_addr
            || self.stcp_server_addr.is_empty()
            || self.stcp_server_addr.chars().any(char::is_whitespace)
        {
            return Err("LAN frps address is invalid".into());
        }
        if let Ok(server_ip) = self.stcp_server_addr.parse::<IpAddr>() {
            if server_ip.is_unspecified() || server_ip.is_multicast() {
                return Err("LAN frps address must identify a concrete host".into());
            }
        }
        if self.stcp_user.trim() != self.stcp_user {
            return Err("STCP user is invalid".into());
        }
        if self.stcp_proxy_name.trim() != self.stcp_proxy_name
            || self.stcp_proxy_name.is_empty()
            || self.stcp_proxy_name.chars().any(char::is_control)
        {
            return Err("STCP proxy name is invalid".into());
        }
        Ok(())
    }
}

pub fn path(root: &Path) -> PathBuf {
    root.join("config.json")
}

pub fn ensure_root(root: &Path) -> Result<(), String> {
    fs::create_dir_all(root).map_err(|_| "Unable to create the Site Agent data directory".into())
}

pub fn load(root: &Path) -> Result<SiteAgentConfig, String> {
    let source = path(root);
    if !source.is_file() {
        return Ok(SiteAgentConfig::default());
    }
    let raw = fs::read_to_string(source)
        .map_err(|_| "Unable to read the Site Agent configuration".to_string())?;
    serde_json::from_str(&raw).map_err(|_| "The Site Agent configuration is invalid".to_string())
}

pub fn save(root: &Path, config: &SiteAgentConfig) -> Result<(), String> {
    ensure_root(root)?;
    let destination = path(root);
    let temporary = destination.with_extension(format!("tmp-{}", std::process::id()));
    let payload = serde_json::to_vec_pretty(config)
        .map_err(|_| "Unable to encode the Site Agent configuration".to_string())?;
    fs::write(&temporary, payload)
        .map_err(|_| "Unable to stage the Site Agent configuration".to_string())?;
    replace_file(&temporary, &destination)
}

#[cfg(windows)]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };
    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination_wide: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    if unsafe {
        MoveFileExW(
            source_wide.as_ptr(),
            destination_wide.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    } == 0
    {
        let _ = fs::remove_file(source);
        return Err("Unable to save the Site Agent configuration".into());
    }
    Ok(())
}

#[cfg(not(windows))]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    if destination.exists() {
        fs::remove_file(destination)
            .map_err(|_| "Unable to replace the Site Agent configuration".to_string())?;
    }
    fs::rename(source, destination)
        .map_err(|_| "Unable to save the Site Agent configuration".to_string())
}

#[cfg(test)]
mod tests {
    use super::SiteAgentConfig;

    #[test]
    fn disabled_defaults_are_safe_and_valid() {
        SiteAgentConfig::default()
            .validate(false, false)
            .expect("disabled default configuration");
    }

    #[test]
    fn enabled_service_requires_a_token() {
        let config = SiteAgentConfig {
            enabled: true,
            ..Default::default()
        };
        assert!(config.validate(false, false).unwrap_err().contains("token"));
    }

    #[test]
    fn lan_stcp_requires_loopback_credentials_and_valid_provider_fields() {
        let mut config = SiteAgentConfig {
            enabled: true,
            transport: "lan-stcp".into(),
            stcp_server_addr: "192.0.2.10".into(),
            stcp_proxy_name: "mklink-field-a".into(),
            ..Default::default()
        };
        assert!(config.validate(true, false).is_err());
        config
            .validate(true, true)
            .expect("valid LAN STCP configuration");

        config.bind_host = "192.0.2.20".into();
        config.allow_lan = true;
        assert!(config.validate(true, true).is_err());
    }
}
