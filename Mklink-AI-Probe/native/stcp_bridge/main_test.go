package main

import "testing"

func validProviderConfig() bridgeConfig {
	return bridgeConfig{
		Mode:       modeProvider,
		ServerAddr: "192.0.2.10",
		ServerPort: 7000,
		AuthToken:  "auth-token",
		User:       "field-a",
		ProxyName:  "mklink-field-a",
		SecretKey:  "stcp-secret",
		LocalAddr:  "127.0.0.1",
		LocalPort:  8766,
	}
}

func TestValidateProviderAllowsOnlyLoopbackBackend(t *testing.T) {
	cfg := validProviderConfig()
	if err := validateConfig(&cfg); err != nil {
		t.Fatalf("valid provider rejected: %v", err)
	}
	cfg.LocalAddr = "192.0.2.20"
	if err := validateConfig(&cfg); err == nil {
		t.Fatal("non-loopback provider backend was accepted")
	}
}

func TestValidateVisitorAllowsOnlyLoopbackListener(t *testing.T) {
	cfg := validProviderConfig()
	cfg.Mode = modeVisitor
	cfg.LocalAddr = ""
	cfg.LocalPort = 0
	cfg.BindAddr = "::1"
	cfg.BindPort = 8767
	if err := validateConfig(&cfg); err != nil {
		t.Fatalf("valid visitor rejected: %v", err)
	}
	cfg.BindAddr = "0.0.0.0"
	if err := validateConfig(&cfg); err == nil {
		t.Fatal("wildcard visitor listener was accepted")
	}
}

func TestNewServiceUsesInMemoryConfiguration(t *testing.T) {
	cfg := validProviderConfig()
	_, err := newService(cfg)
	if err != nil {
		t.Fatalf("new in-memory service: %v", err)
	}
}
