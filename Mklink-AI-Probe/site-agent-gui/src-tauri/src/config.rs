use serde::{Deserialize, Serialize};
use std::fs;
use std::net::IpAddr;
use std::path::{Path, PathBuf};

const CONFIG_SCHEMA: &str = "mklink.site-agent.config.v1";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SiteConfig {
    pub schema: String,
    pub mode: String,
    #[serde(default = "default_transport")]
    pub transport: String,
    pub bind_host: String,
    pub port: u16,
    pub allow_lan: bool,
    pub project_root: String,
    pub start_core_on_launch: bool,
    #[serde(default)]
    pub stcp_server_addr: String,
    #[serde(default = "default_stcp_server_port")]
    pub stcp_server_port: u16,
    #[serde(default)]
    pub stcp_user: String,
    #[serde(default)]
    pub stcp_proxy_name: String,
}

fn default_transport() -> String {
    "direct".into()
}

fn default_stcp_server_port() -> u16 {
    7000
}

impl SiteConfig {
    pub fn defaults(portable_root: &Path) -> Self {
        Self {
            schema: CONFIG_SCHEMA.into(),
            mode: "portable".into(),
            transport: default_transport(),
            bind_host: "127.0.0.1".into(),
            port: 8766,
            allow_lan: false,
            project_root: portable_root.to_string_lossy().into_owned(),
            start_core_on_launch: true,
            stcp_server_addr: String::new(),
            stcp_server_port: default_stcp_server_port(),
            stcp_user: String::new(),
            stcp_proxy_name: String::new(),
        }
    }

    pub fn validate(
        &self,
        token_configured: bool,
        stcp_credentials_configured: bool,
    ) -> Result<(), String> {
        if self.schema != CONFIG_SCHEMA || self.mode != "portable" {
            return Err("不支持的现场端配置格式或运行模式".into());
        }
        if self.transport != "direct" && self.transport != "lan-stcp" {
            return Err("Transport must be direct or lan-stcp".into());
        }
        if self.bind_host.trim() != self.bind_host || self.bind_host.is_empty() {
            return Err("监听地址无效".into());
        }
        if self.port == 0 {
            return Err("Site Agent port must be in 1..65535".into());
        }
        let address: IpAddr = self
            .bind_host
            .parse()
            .map_err(|_| "监听地址必须是本机 IP 地址".to_string())?;
        if address.is_unspecified() || address.is_multicast() {
            return Err("禁止 wildcard、unspecified 或 multicast 监听地址".into());
        }
        if !address.is_loopback() && (!self.allow_lan || !token_configured) {
            return Err("LAN/VPN 地址要求勾选直连并先生成访问令牌".into());
        }
        if self.transport == "lan-stcp" {
            if !address.is_loopback() || self.allow_lan {
                return Err("LAN STCP requires a loopback Site Agent listener".into());
            }
            if !token_configured || !stcp_credentials_configured {
                return Err(
                    "LAN STCP requires Site Agent, FRP auth, and STCP credentials"
                        .into(),
                );
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
            if self.stcp_server_port == 0 {
                return Err("LAN frps port must be in 1..65535".into());
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
        }
        let project = Path::new(&self.project_root);
        if !project.is_absolute() || !project.is_dir() {
            return Err("现场工程目录必须是已存在的绝对目录".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::SiteConfig;

    #[test]
    fn lan_stcp_requires_loopback_and_credentials() {
        let root = std::env::current_dir().expect("current directory");
        let mut config = SiteConfig::defaults(&root);
        config.transport = "lan-stcp".into();
        config.stcp_server_addr = "192.0.2.10".into();
        config.stcp_proxy_name = "mklink-field-a".into();
        assert!(config.validate(true, false).is_err());
        assert!(config.validate(true, true).is_ok());

        config.bind_host = "192.0.2.20".into();
        config.allow_lan = true;
        assert!(config.validate(true, true).is_err());
    }
}

pub fn load(root: &Path) -> Result<SiteConfig, String> {
    let path = config_path(root);
    if !path.exists() {
        return Ok(SiteConfig::defaults(root));
    }
    let bytes = fs::read(&path).map_err(|_| "无法读取现场端配置".to_string())?;
    serde_json::from_slice(&bytes).map_err(|_| "现场端配置已损坏".to_string())
}

pub fn save(root: &Path, config: &SiteConfig) -> Result<(), String> {
    let data = serde_json::to_vec_pretty(config).map_err(|_| "无法编码现场端配置".to_string())?;
    atomic_write(&config_path(root), &data)
}

pub fn config_path(root: &Path) -> PathBuf {
    root.join("data").join("config.json")
}

pub fn ready_path(root: &Path) -> PathBuf {
    root.join("data").join("ready.json")
}

pub fn ensure_data_root(root: &Path) -> Result<(), String> {
    let data = root.join("data");
    fs::create_dir_all(data.join("logs")).map_err(|_| "便携目录不可写".to_string())?;
    let probe = data.join(".write-test");
    fs::write(&probe, b"ok").map_err(|_| "便携目录不可写".to_string())?;
    fs::remove_file(probe).map_err(|_| "便携目录不可写".to_string())
}

fn atomic_write(path: &Path, data: &[u8]) -> Result<(), String> {
    let parent = path.parent().ok_or_else(|| "配置路径无效".to_string())?;
    fs::create_dir_all(parent).map_err(|_| "便携目录不可写".to_string())?;
    let temporary = path.with_extension(format!("tmp-{}", std::process::id()));
    {
        use std::io::Write;
        let mut file = fs::File::create(&temporary).map_err(|_| "便携目录不可写".to_string())?;
        file.write_all(data).map_err(|_| "无法写入配置".to_string())?;
        file.sync_all().map_err(|_| "无法刷新配置".to_string())?;
    }
    replace_file(&temporary, path)?;
    Ok(())
}

#[cfg(windows)]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };
    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination_wide: Vec<u16> = destination.as_os_str().encode_wide().chain(Some(0)).collect();
    let result = unsafe {
        MoveFileExW(
            source_wide.as_ptr(),
            destination_wide.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if result == 0 {
        let _ = fs::remove_file(source);
        return Err("无法原子替换配置".into());
    }
    Ok(())
}

#[cfg(not(windows))]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    if destination.exists() {
        fs::remove_file(destination).map_err(|_| "无法替换配置".to_string())?;
    }
    fs::rename(source, destination).map_err(|_| "无法替换配置".to_string())
}
