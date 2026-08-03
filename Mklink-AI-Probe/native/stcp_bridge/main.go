// Package main exposes the official FRP client as a small in-process C ABI.
//
// The resulting mklink-stcp.dll is loaded by the Site Agent process. It does
// not extract, execute, rename, or otherwise depend on frpc.exe.
package main

/*
#include <stdlib.h>
*/
import "C"

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unsafe"

	"github.com/fatedier/frp/client"
	"github.com/fatedier/frp/client/proxy"
	"github.com/fatedier/frp/pkg/config/source"
	v1 "github.com/fatedier/frp/pkg/config/v1"
	frplog "github.com/fatedier/frp/pkg/util/log"
)

const (
	modeProvider = "provider"
	modeVisitor  = "visitor"
)

type bridgeConfig struct {
	Mode       string `json:"mode"`
	ServerAddr string `json:"server_addr"`
	ServerPort int    `json:"server_port"`
	AuthToken  string `json:"auth_token"`
	User       string `json:"user"`
	ProxyName  string `json:"proxy_name"`
	SecretKey  string `json:"secret_key"`
	LocalAddr  string `json:"local_addr"`
	LocalPort  int    `json:"local_port"`
	BindAddr   string `json:"bind_addr"`
	BindPort   int    `json:"bind_port"`
}

type session struct {
	service   *client.Service
	cancel    context.CancelFunc
	done      chan struct{}
	mode      string
	proxyName string
	bindAddr  string
	bindPort  int
	stateMu   sync.RWMutex
	runError  string
	stopped   bool
}

type sessionStatus struct {
	State     string `json:"state"`
	Mode      string `json:"mode"`
	Ready     bool   `json:"ready"`
	Error     string `json:"error,omitempty"`
	ProxyName string `json:"proxy_name,omitempty"`
	BindAddr  string `json:"bind_addr,omitempty"`
	BindPort  int    `json:"bind_port,omitempty"`
}

var (
	nextHandle atomic.Uint64
	sessionsMu sync.RWMutex
	sessions   = make(map[uint64]*session)
	lastErrMu  sync.Mutex
	lastErr    string
	loggerOnce sync.Once
)

func setLastError(err error) {
	lastErrMu.Lock()
	defer lastErrMu.Unlock()
	if err == nil {
		lastErr = ""
		return
	}
	lastErr = err.Error()
}

func validatePort(name string, value int) error {
	if value < 1 || value > 65535 {
		return fmt.Errorf("%s must be in 1..65535", name)
	}
	return nil
}

func validateLoopback(name, value string) error {
	ip := net.ParseIP(value)
	if ip == nil || !ip.IsLoopback() {
		return fmt.Errorf("%s must be a loopback IP address", name)
	}
	return nil
}

func validateConfig(cfg *bridgeConfig) error {
	cfg.Mode = strings.TrimSpace(cfg.Mode)
	cfg.ServerAddr = strings.TrimSpace(cfg.ServerAddr)
	cfg.User = strings.TrimSpace(cfg.User)
	cfg.ProxyName = strings.TrimSpace(cfg.ProxyName)
	cfg.LocalAddr = strings.TrimSpace(cfg.LocalAddr)
	cfg.BindAddr = strings.TrimSpace(cfg.BindAddr)
	if cfg.Mode != modeProvider && cfg.Mode != modeVisitor {
		return errors.New("mode must be provider or visitor")
	}
	if cfg.ServerAddr == "" {
		return errors.New("server_addr is required")
	}
	if err := validatePort("server_port", cfg.ServerPort); err != nil {
		return err
	}
	if cfg.AuthToken == "" {
		return errors.New("auth_token is required")
	}
	if cfg.ProxyName == "" {
		return errors.New("proxy_name is required")
	}
	if cfg.SecretKey == "" {
		return errors.New("secret_key is required")
	}
	if strings.ContainsAny(cfg.ProxyName, "\r\n\t") {
		return errors.New("proxy_name contains invalid whitespace")
	}
	switch cfg.Mode {
	case modeProvider:
		if err := validateLoopback("local_addr", cfg.LocalAddr); err != nil {
			return err
		}
		return validatePort("local_port", cfg.LocalPort)
	case modeVisitor:
		if err := validateLoopback("bind_addr", cfg.BindAddr); err != nil {
			return err
		}
		return validatePort("bind_port", cfg.BindPort)
	default:
		panic("validated mode has no implementation")
	}
}

func newService(cfg bridgeConfig) (*client.Service, error) {
	loggerOnce.Do(func() {
		frplog.InitLogger("disable", "warn", 1, true)
	})
	loginFailExit := true
	common := &v1.ClientCommonConfig{
		ServerAddr:    cfg.ServerAddr,
		ServerPort:    cfg.ServerPort,
		User:          cfg.User,
		LoginFailExit: &loginFailExit,
		Auth: v1.AuthClientConfig{
			Method: v1.AuthMethodToken,
			Token:  cfg.AuthToken,
		},
		Log: v1.LogConfig{
			To:    "disable",
			Level: "warn",
		},
	}
	configSource := source.NewConfigSource()
	var proxies []v1.ProxyConfigurer
	var visitors []v1.VisitorConfigurer
	if cfg.Mode == modeProvider {
		proxies = []v1.ProxyConfigurer{
			&v1.STCPProxyConfig{
				ProxyBaseConfig: v1.ProxyBaseConfig{
					Name: cfg.ProxyName,
					Type: string(v1.ProxyTypeSTCP),
					ProxyBackend: v1.ProxyBackend{
						LocalIP:   cfg.LocalAddr,
						LocalPort: cfg.LocalPort,
					},
				},
				Secretkey: cfg.SecretKey,
			},
		}
	} else {
		visitors = []v1.VisitorConfigurer{
			&v1.STCPVisitorConfig{
				VisitorBaseConfig: v1.VisitorBaseConfig{
					Name:       cfg.ProxyName + "-visitor",
					Type:       string(v1.VisitorTypeSTCP),
					SecretKey:  cfg.SecretKey,
					ServerName: cfg.ProxyName,
					BindAddr:   cfg.BindAddr,
					BindPort:   cfg.BindPort,
				},
			},
		}
	}
	if err := configSource.ReplaceAll(proxies, visitors); err != nil {
		return nil, err
	}
	return client.NewService(client.ServiceOptions{
		Common:                 common,
		ConfigSourceAggregator: source.NewAggregator(configSource),
	})
}

func (s *session) setRunResult(err error) {
	s.stateMu.Lock()
	defer s.stateMu.Unlock()
	if err != nil && !errors.Is(err, context.Canceled) {
		s.runError = err.Error()
	}
	s.stopped = true
}

func (s *session) ready() (bool, string) {
	s.stateMu.RLock()
	if s.runError != "" {
		err := s.runError
		s.stateMu.RUnlock()
		return false, err
	}
	if s.stopped {
		s.stateMu.RUnlock()
		return false, "STCP client stopped before becoming ready"
	}
	s.stateMu.RUnlock()
	if s.mode == modeProvider {
		status, ok := s.service.StatusExporter().GetProxyStatus(s.proxyName)
		if !ok {
			return false, ""
		}
		if status.Err != "" {
			return false, status.Err
		}
		return status.Phase == proxy.ProxyPhaseRunning, ""
	}
	address := net.JoinHostPort(s.bindAddr, strconv.Itoa(s.bindPort))
	conn, err := net.DialTimeout("tcp", address, 100*time.Millisecond)
	if err != nil {
		return false, ""
	}
	_ = conn.Close()
	return true, ""
}

func startSession(cfg bridgeConfig) (uint64, error) {
	if err := validateConfig(&cfg); err != nil {
		return 0, err
	}
	service, err := newService(cfg)
	if err != nil {
		return 0, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	s := &session{
		service:   service,
		cancel:    cancel,
		done:      make(chan struct{}),
		mode:      cfg.Mode,
		proxyName: cfg.ProxyName,
		bindAddr:  cfg.BindAddr,
		bindPort:  cfg.BindPort,
	}
	handle := nextHandle.Add(1)
	sessionsMu.Lock()
	sessions[handle] = s
	sessionsMu.Unlock()
	go func() {
		defer close(s.done)
		s.setRunResult(service.Run(ctx))
	}()

	deadline := time.Now().Add(12 * time.Second)
	for time.Now().Before(deadline) {
		ready, readinessErr := s.ready()
		if readinessErr != "" {
			stopSession(handle)
			return 0, errors.New(readinessErr)
		}
		if ready {
			return handle, nil
		}
		select {
		case <-s.done:
		default:
		}
		time.Sleep(50 * time.Millisecond)
	}
	stopSession(handle)
	return 0, errors.New("timed out waiting for STCP client readiness")
}

func getSession(handle uint64) (*session, bool) {
	sessionsMu.RLock()
	defer sessionsMu.RUnlock()
	s, ok := sessions[handle]
	return s, ok
}

func stopSession(handle uint64) bool {
	sessionsMu.Lock()
	s, ok := sessions[handle]
	if ok {
		delete(sessions, handle)
	}
	sessionsMu.Unlock()
	if !ok {
		return false
	}
	s.cancel()
	s.service.Close()
	select {
	case <-s.done:
	case <-time.After(5 * time.Second):
	}
	return true
}

func statusJSON(handle uint64) ([]byte, error) {
	s, ok := getSession(handle)
	if !ok {
		return nil, errors.New("unknown STCP session handle")
	}
	ready, readinessErr := s.ready()
	status := sessionStatus{
		State:     "starting",
		Mode:      s.mode,
		Ready:     ready,
		ProxyName: s.proxyName,
		BindAddr:  s.bindAddr,
		BindPort:  s.bindPort,
	}
	if ready {
		status.State = "ready"
	}
	if readinessErr != "" {
		status.State = "failed"
		status.Error = readinessErr
	}
	return json.Marshal(status)
}

//export MklinkSTCPStart
func MklinkSTCPStart(configJSON *C.char) C.ulonglong {
	setLastError(nil)
	if configJSON == nil {
		setLastError(errors.New("config JSON is required"))
		return 0
	}
	var cfg bridgeConfig
	if err := json.Unmarshal([]byte(C.GoString(configJSON)), &cfg); err != nil {
		setLastError(errors.New("invalid STCP config JSON"))
		return 0
	}
	handle, err := startSession(cfg)
	if err != nil {
		setLastError(err)
		return 0
	}
	return C.ulonglong(handle)
}

//export MklinkSTCPStop
func MklinkSTCPStop(handle C.ulonglong) C.int {
	if stopSession(uint64(handle)) {
		return 1
	}
	return 0
}

//export MklinkSTCPStatus
func MklinkSTCPStatus(handle C.ulonglong) *C.char {
	value, err := statusJSON(uint64(handle))
	if err != nil {
		setLastError(err)
		return nil
	}
	return C.CString(string(value))
}

//export MklinkSTCPLastError
func MklinkSTCPLastError() *C.char {
	lastErrMu.Lock()
	defer lastErrMu.Unlock()
	return C.CString(lastErr)
}

//export MklinkSTCPFree
func MklinkSTCPFree(value *C.char) {
	C.free(unsafe.Pointer(value))
}

func main() {}
