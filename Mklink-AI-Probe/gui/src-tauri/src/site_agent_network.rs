use std::collections::BTreeSet;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

pub fn local_bind_addresses() -> Vec<String> {
    let mut addresses = BTreeSet::new();
    addresses.insert(IpAddr::V4(Ipv4Addr::LOCALHOST));
    addresses.insert(IpAddr::V6(Ipv6Addr::LOCALHOST));
    if let Ok(interfaces) = get_if_addrs::get_if_addrs() {
        for interface in interfaces {
            let address = interface.ip();
            if usable_bind(address) {
                addresses.insert(address);
            }
        }
    }
    addresses
        .into_iter()
        .map(|address| address.to_string())
        .collect()
}

fn usable_bind(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(value) => {
            !value.is_unspecified()
                && !value.is_multicast()
                && !value.is_link_local()
                && !value.is_broadcast()
        }
        IpAddr::V6(value) => {
            !value.is_unspecified() && !value.is_multicast() && !value.is_unicast_link_local()
        }
    }
}

pub fn is_local_bind(address: &str) -> bool {
    let Ok(expected) = address.parse::<IpAddr>() else {
        return false;
    };
    local_bind_addresses()
        .iter()
        .filter_map(|item| item.parse::<IpAddr>().ok())
        .any(|item| item == expected)
}
