#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    mklink_site_agent_lib::run();
}
