use base64::{engine::general_purpose::STANDARD, Engine as _};
use rand::RngCore;
use serde::Serialize;
use serde_json::{json, Value};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

const MAX_FRAME: usize = 1024 * 1024;

#[derive(Clone, Debug, Serialize)]
pub struct ProbeSummary {
    pub device: String,
    pub description: String,
    pub manufacturer: String,
    pub selected: bool,
}

pub struct RemoteStatus {
    pub ready: bool,
    pub listener: bool,
    pub probe_connected: bool,
    pub host: String,
    pub port: u16,
}

pub fn status(host: &str, port: u16, token: &str) -> Result<RemoteStatus, String> {
    let value = call(host, port, token, "agent.status")?;
    Ok(RemoteStatus {
        ready: value.get("ready").and_then(Value::as_bool).unwrap_or(false),
        listener: value.get("listener").and_then(Value::as_bool).unwrap_or(false),
        probe_connected: value
            .get("probe_connected")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        host: value.get("host").and_then(Value::as_str).unwrap_or("").to_owned(),
        port: value
            .get("port")
            .and_then(Value::as_u64)
            .and_then(|value| u16::try_from(value).ok())
            .unwrap_or_default(),
    })
}

pub fn ports(host: &str, port: u16, token: &str) -> Result<Vec<ProbeSummary>, String> {
    let value = call(host, port, token, "agent.ports")?;
    let values = value
        .as_array()
        .ok_or_else(|| "Site Agent returned an invalid probe list".to_string())?;
    Ok(values
        .iter()
        .filter_map(|value| {
            let device = value.get("device")?.as_str()?.chars().take(64).collect();
            Some(ProbeSummary {
                device,
                description: value
                    .get("description")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .chars()
                    .take(160)
                    .collect(),
                manufacturer: value
                    .get("manufacturer")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .chars()
                    .take(80)
                    .collect(),
                selected: false,
            })
        })
        .collect())
}

fn call(host: &str, port: u16, token: &str, method: &str) -> Result<Value, String> {
    let deadline = Instant::now() + Duration::from_secs(3);
    let address = (host, port)
        .to_socket_addrs()
        .map_err(|_| "Site Agent address is invalid".to_string())?
        .next()
        .ok_or_else(|| "Site Agent address is unavailable".to_string())?;
    let mut stream = TcpStream::connect_timeout(&address, remaining(deadline)?)
        .map_err(|_| "Unable to connect to the Site Agent".to_string())?;

    let mut nonce = [0_u8; 16];
    rand::thread_rng().fill_bytes(&mut nonce);
    let key = STANDARD.encode(nonce);
    let authority = if host.contains(':') {
        format!("[{host}]:{port}")
    } else {
        format!("{host}:{port}")
    };
    let request = format!(
        "GET / HTTP/1.1\r\nHost: {authority}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    );
    write_all(&mut stream, request.as_bytes(), deadline)
        .map_err(|_| "Unable to negotiate Site Agent transport".to_string())?;
    let headers = read_headers(&mut stream, deadline)?;
    validate_upgrade(&headers, &key)?;

    send_json(
        &mut stream,
        &json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "system.handshake",
            "params": {"protocol_version": "1.0", "token": token}
        }),
        deadline,
    )?;
    let handshake = receive_json(&mut stream, deadline)?;
    let version = result(&handshake, 1)?
        .get("protocol_version")
        .and_then(Value::as_str)
        .unwrap_or("");
    if version.split('.').next() != Some("1") {
        return Err("Site Agent protocol is incompatible".into());
    }

    send_json(
        &mut stream,
        &json!({"jsonrpc":"2.0","id":2,"method":method,"params":{}}),
        deadline,
    )?;
    let response = receive_json(&mut stream, deadline)?;
    Ok(result(&response, 2)?.clone())
}

fn result(value: &Value, id: u64) -> Result<&Value, String> {
    if value.get("id").and_then(Value::as_u64) != Some(id) {
        return Err("Site Agent returned a mismatched response".into());
    }
    if value.get("error").is_some() {
        return Err("Site Agent rejected the authenticated operation".into());
    }
    value
        .get("result")
        .ok_or_else(|| "Site Agent returned an incomplete response".to_string())
}

fn read_headers(stream: &mut TcpStream, deadline: Instant) -> Result<String, String> {
    let mut bytes = Vec::new();
    let mut byte = [0_u8; 1];
    while bytes.len() < 8192 {
        read_exact(stream, &mut byte, deadline)
            .map_err(|_| "Site Agent transport upgrade was incomplete".to_string())?;
        bytes.push(byte[0]);
        if bytes.ends_with(b"\r\n\r\n") {
            return String::from_utf8(bytes)
                .map_err(|_| "Site Agent transport upgrade was invalid".to_string());
        }
    }
    Err("Site Agent transport headers exceeded the limit".into())
}

fn validate_upgrade(headers: &str, key: &str) -> Result<(), String> {
    let mut lines = headers.split("\r\n");
    if !lines.next().unwrap_or("").contains(" 101 ") {
        return Err("Site Agent did not accept the WebSocket upgrade".into());
    }
    let accept = lines.find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("Sec-WebSocket-Accept")
            .then(|| value.trim())
    });
    let expected = STANDARD.encode(sha1(
        format!("{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11").as_bytes(),
    ));
    if accept != Some(expected.as_str()) {
        return Err("Site Agent WebSocket identity check failed".into());
    }
    Ok(())
}

fn send_json(stream: &mut TcpStream, value: &Value, deadline: Instant) -> Result<(), String> {
    let payload = serde_json::to_vec(value)
        .map_err(|_| "Unable to encode Site Agent request".to_string())?;
    let mut frame = vec![0x81];
    let length = payload.len();
    if length < 126 {
        frame.push(0x80 | length as u8);
    } else if length <= u16::MAX as usize {
        frame.push(0x80 | 126);
        frame.extend_from_slice(&(length as u16).to_be_bytes());
    } else {
        return Err("Site Agent request exceeded the limit".into());
    }
    let mut mask = [0_u8; 4];
    rand::thread_rng().fill_bytes(&mut mask);
    frame.extend_from_slice(&mask);
    frame.extend(payload.iter().enumerate().map(|(index, byte)| byte ^ mask[index % 4]));
    write_all(stream, &frame, deadline)
        .map_err(|_| "Unable to send Site Agent request".to_string())
}

fn receive_json(stream: &mut TcpStream, deadline: Instant) -> Result<Value, String> {
    let mut head = [0_u8; 2];
    read_exact(stream, &mut head, deadline)
        .map_err(|_| "Site Agent response was incomplete".to_string())?;
    if head[0] & 0x0f != 1 || head[0] & 0x80 == 0 || head[1] & 0x80 != 0 {
        return Err("Site Agent returned an unsupported WebSocket frame".into());
    }
    let mut length = (head[1] & 0x7f) as usize;
    if length == 126 {
        let mut value = [0_u8; 2];
        read_exact(stream, &mut value, deadline)
            .map_err(|_| "Site Agent response was incomplete".to_string())?;
        length = u16::from_be_bytes(value) as usize;
    } else if length == 127 {
        let mut value = [0_u8; 8];
        read_exact(stream, &mut value, deadline)
            .map_err(|_| "Site Agent response was incomplete".to_string())?;
        length = usize::try_from(u64::from_be_bytes(value))
            .map_err(|_| "Site Agent response exceeded the limit".to_string())?;
    }
    if length > MAX_FRAME {
        return Err("Site Agent response exceeded the limit".into());
    }
    let mut payload = vec![0_u8; length];
    read_exact(stream, &mut payload, deadline)
        .map_err(|_| "Site Agent response was incomplete".to_string())?;
    serde_json::from_slice(&payload).map_err(|_| "Site Agent response was invalid".to_string())
}

fn remaining(deadline: Instant) -> Result<Duration, String> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero())
        .ok_or_else(|| "Site Agent operation exceeded its absolute deadline".to_string())
}

fn read_exact(
    stream: &mut TcpStream,
    buffer: &mut [u8],
    deadline: Instant,
) -> Result<(), String> {
    let mut offset = 0;
    while offset < buffer.len() {
        let timeout = remaining(deadline)?;
        stream
            .set_read_timeout(Some(timeout))
            .map_err(|_| "Unable to configure Site Agent read deadline".to_string())?;
        let count = stream
            .read(&mut buffer[offset..])
            .map_err(|_| "Site Agent read did not complete before the deadline".to_string())?;
        if count == 0 {
            return Err("Site Agent closed before the response completed".into());
        }
        offset += count;
    }
    Ok(())
}

fn write_all(stream: &mut TcpStream, buffer: &[u8], deadline: Instant) -> Result<(), String> {
    let mut offset = 0;
    while offset < buffer.len() {
        let timeout = remaining(deadline)?;
        stream
            .set_write_timeout(Some(timeout))
            .map_err(|_| "Unable to configure Site Agent write deadline".to_string())?;
        let count = stream
            .write(&buffer[offset..])
            .map_err(|_| "Site Agent write did not complete before the deadline".to_string())?;
        if count == 0 {
            return Err("Site Agent closed before the request completed".into());
        }
        offset += count;
    }
    Ok(())
}

fn sha1(input: &[u8]) -> [u8; 20] {
    let mut data = input.to_vec();
    let bit_len = (data.len() as u64) * 8;
    data.push(0x80);
    while data.len() % 64 != 56 {
        data.push(0);
    }
    data.extend_from_slice(&bit_len.to_be_bytes());
    let mut h = [0x67452301_u32, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0];
    for block in data.chunks_exact(64) {
        let mut w = [0_u32; 80];
        for (index, chunk) in block.chunks_exact(4).enumerate() {
            w[index] = u32::from_be_bytes(chunk.try_into().unwrap());
        }
        for index in 16..80 {
            w[index] = (w[index - 3] ^ w[index - 8] ^ w[index - 14] ^ w[index - 16]).rotate_left(1);
        }
        let (mut a, mut b, mut c, mut d, mut e) = (h[0], h[1], h[2], h[3], h[4]);
        for (index, word) in w.into_iter().enumerate() {
            let (f, k) = match index {
                0..=19 => ((b & c) | ((!b) & d), 0x5a827999),
                20..=39 => (b ^ c ^ d, 0x6ed9eba1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8f1bbcdc),
                _ => (b ^ c ^ d, 0xca62c1d6),
            };
            let next = a
                .rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(word);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = next;
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
    }
    let mut result = [0_u8; 20];
    for (index, value) in h.into_iter().enumerate() {
        result[index * 4..index * 4 + 4].copy_from_slice(&value.to_be_bytes());
    }
    result
}
