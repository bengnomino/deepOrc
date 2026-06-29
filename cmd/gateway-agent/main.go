// Static gateway agent for OpenWrt/Alpine containers (no Python).
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type config struct {
	Token         string
	OrchAllowedIP string
	ListenHost    string
	ListenPort    string
	WGInterface   string
	NetInterface  string
	NFTTable      string
}

func loadConfig() config {
	c := config{
		Token:         os.Getenv("AGENT_TOKEN"),
		OrchAllowedIP: getenv("ORCH_ALLOWED_IP", "10.10.0.1"),
		ListenHost:    getenv("LISTEN_HOST", "0.0.0.0"),
		ListenPort:    getenv("LISTEN_PORT", "8081"),
		WGInterface:   getenv("WG_INTERFACE", "wg0"),
		NetInterface:  getenv("NET_INTERFACE", "eth0"),
		NFTTable:      getenv("NFT_SUSPEND_TABLE", "inet wg_suspend"),
	}
	if c.Token == "" {
		if b, err := os.ReadFile("/opt/gateway-agent/config.env"); err == nil {
			for _, line := range strings.Split(string(b), "\n") {
				line = strings.TrimSpace(line)
				if line == "" || strings.HasPrefix(line, "#") {
					continue
				}
				k, v, ok := strings.Cut(line, "=")
				if !ok {
					continue
				}
				switch k {
				case "AGENT_TOKEN":
					c.Token = v
				case "ORCH_ALLOWED_IP":
					c.OrchAllowedIP = v
				case "LISTEN_HOST":
					c.ListenHost = v
				case "LISTEN_PORT":
					c.ListenPort = v
				case "NET_INTERFACE":
					c.NetInterface = v
				}
			}
		}
	}
	return c
}

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func run(name string, args ...string) (string, error) {
	cmd := exec.Command(name, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		msg := strings.TrimSpace(string(out))
		if msg == "" {
			msg = err.Error()
		}
		return "", fmt.Errorf("%s", msg)
	}
	return string(out), nil
}

func runOK(name string, args ...string) error {
	_, err := run(name, args...)
	return err
}

func auth(cfg config, r *http.Request) bool {
	h := r.Header.Get("Authorization")
	return h == "Bearer "+cfg.Token
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func readJSON(r *http.Request, v any) error {
	defer r.Body.Close()
	b, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		return err
	}
	return json.Unmarshal(b, v)
}

type peerInfo struct {
	PublicKey     string  `json:"public_key"`
	AllowedIPs    string  `json:"allowed_ips"`
	Endpoint      *string `json:"endpoint"`
	LastHandshake *string `json:"last_handshake"`
	RxBytes       int     `json:"rx_bytes"`
	TxBytes       int     `json:"tx_bytes"`
}

func listPeers(iface string) ([]peerInfo, error) {
	out, err := run("wg", "show", iface, "dump")
	if err != nil {
		return nil, err
	}
	lines := strings.Split(strings.TrimSpace(out), "\n")
	if len(lines) <= 1 {
		return []peerInfo{}, nil
	}
	var peers []peerInfo
	for _, line := range lines[1:] {
		parts := strings.Split(line, "\t")
		if len(parts) < 8 {
			continue
		}
		var ep *string
		if parts[2] != "(none)" {
			ep = &parts[2]
		}
		var hs *string
		if v, _ := strconv.ParseInt(parts[4], 10, 64); v > 0 {
			s := time.Unix(v, 0).UTC().Format(time.RFC3339)
			hs = &s
		}
		rx, _ := strconv.Atoi(parts[5])
		tx, _ := strconv.Atoi(parts[6])
		peers = append(peers, peerInfo{
			PublicKey: parts[0], AllowedIPs: parts[3], Endpoint: ep,
			LastHandshake: hs, RxBytes: rx, TxBytes: tx,
		})
	}
	return peers, nil
}

func wgOnline(iface string) bool {
	return runOK("wg", "show", iface) == nil
}

func tailscaleOnline() bool {
	out, err := run("tailscale", "status", "--json")
	if err != nil {
		return false
	}
	return strings.Contains(out, `"BackendState": "Running"`) || strings.Contains(out, `"Online": true`)
}

func nftRunning() bool {
	return runOK("nft", "list", "ruleset") == nil
}

func exitNodeIDFromEnv() string {
	b, err := os.ReadFile("/opt/gateway-agent/exit-node.env")
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "EXIT_NODE_ID=") {
			return strings.TrimSpace(strings.TrimPrefix(line, "EXIT_NODE_ID="))
		}
	}
	return ""
}

func exitNodeConfigured() bool {
	return exitNodeIDFromEnv() != ""
}

func ensureSuspendTable(table string) error {
	parts := strings.Fields(table)
	if len(parts) != 2 {
		return fmt.Errorf("invalid nft table %q", table)
	}
	_ = runOK("nft", append([]string{"add", "table"}, parts...)...)
	chain := append([]string{"add", "chain"}, parts...)
	chain = append(chain, "forward", "{", "type", "filter", "hook", "forward", "priority", "filter", ";", "policy", "accept", ";", "}")
	return runOK("nft", chain...)
}

func suspendPeerIP(table, ip string) error {
	if err := ensureSuspendTable(table); err != nil {
		return err
	}
	parts := strings.Fields(table)
	rule := append([]string{"add", "rule"}, parts...)
	rule = append(rule, "forward", "ip", "daddr", ip, "drop")
	return runOK("nft", rule...)
}

func resumePeerIP(table, ip string) error {
	parts := strings.Fields(table)
	args := append([]string{"-a", "list", "chain"}, parts...)
	args = append(args, "forward")
	out, err := run("nft", args...)
	if err != nil {
		return nil
	}
	for _, line := range strings.Split(out, "\n") {
		if strings.Contains(line, ip) && strings.Contains(line, "drop") {
			f := strings.Fields(line)
			handle := f[len(f)-1]
			del := append([]string{"delete", "rule"}, parts...)
			del = append(del, "forward", "handle", handle)
			_ = runOK("nft", del...)
		}
	}
	return nil
}

var reInet = regexp.MustCompile(`\sinet\s(\S+)`)

func vmLANIP() (string, error) {
	out, err := run("ip", "-4", "-o", "addr", "show", "scope", "global")
	if err == nil {
		for _, line := range strings.Split(out, "\n") {
			if m := reInet.FindStringSubmatch(line); m != nil && strings.HasPrefix(m[1], "10.10.") {
				return strings.Split(m[1], "/")[0], nil
			}
		}
	}
	out, err = run("ip", "-4", "route", "get", "1.1.1.1")
	if err != nil {
		return "", err
	}
	parts := strings.Fields(out)
	for i, p := range parts {
		if p == "src" && i+1 < len(parts) {
			return parts[i+1], nil
		}
	}
	return "", fmt.Errorf("could not detect LAN IP")
}

func wgConfAddress() (string, string, error) {
	b, err := os.ReadFile("/etc/wireguard/wg0.conf")
	if err != nil {
		return "", "", err
	}
	var addr string
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "Address") {
			addr = strings.TrimSpace(strings.SplitN(line, "=", 2)[1])
			break
		}
	}
	if addr == "" {
		return "", "", fmt.Errorf("no Address in wg0.conf")
	}
	ip, pref, _ := strings.Cut(addr, "/")
	if pref == "" {
		pref = "24"
	}
	o := strings.Split(ip, ".")
	if len(o) != 4 {
		return "", "", fmt.Errorf("invalid wg Address")
	}
	return ip, fmt.Sprintf("%s.%s.%s.0/%s", o[0], o[1], o[2], pref), nil
}

func wgSubnet(iface string) string {
	out, _ := run("ip", "-4", "-o", "addr", "show", "dev", iface)
	for _, line := range strings.Split(out, "\n") {
		if m := reInet.FindStringSubmatch(line); m != nil {
			ip, pref, _ := strings.Cut(m[1], "/")
			o := strings.Split(ip, ".")
			if len(o) == 4 {
				return fmt.Sprintf("%s.%s.%s.0/%s", o[0], o[1], o[2], pref)
			}
		}
	}
	if _, subnet, err := wgConfAddress(); err == nil {
		return subnet
	}
	return "10.64.2.0/24"
}

func wgGatewayIP(iface string) (string, error) {
	out, err := run("ip", "-4", "-o", "addr", "show", "dev", iface)
	if err == nil {
		for _, line := range strings.Split(out, "\n") {
			if m := reInet.FindStringSubmatch(line); m != nil {
				return strings.Split(m[1], "/")[0], nil
			}
		}
	}
	if ip, _, err := wgConfAddress(); err == nil {
		return ip, nil
	}
	return "", fmt.Errorf("no wg address")
}

func ipRule(pref string, args ...string) {
	_ = runOK("ip", append([]string{"rule", "del", "pref", pref}, args...)...)
	_ = runOK("ip", append([]string{"rule", "add", "pref", pref}, args...)...)
}

const tailscaleSNATMark = "0x400"

func removeCustomTailscaleMasquerade() {
	out, err := run("nft", "-a", "list", "chain", "ip", "gw_nat", "postrouting")
	tableName := "gw_nat"
	if err != nil {
		out, err = run("nft", "-a", "list", "chain", "ip", "nat", "postrouting")
		tableName = "nat"
	}
	if err != nil {
		return
	}
	for _, line := range strings.Split(out, "\n") {
		if strings.Contains(line, "tailscale0") && strings.Contains(line, "masquerade") {
			fields := strings.Fields(line)
			if len(fields) == 0 {
				continue
			}
			handle := fields[len(fields)-1]
			if _, err := strconv.Atoi(handle); err == nil {
				_ = runOK("nft", "delete", "rule", "ip", tableName, "postrouting", "handle", handle)
			}
		}
	}
}

func ensureWgTailscaleForwardMark() {
	markRule := "iifname wg0 oifname tailscale0 meta mark set " + tailscaleSNATMark
	if out, err := run("nft", "list", "chain", "ip", "gw_mangle", "forward"); err == nil {
		if strings.Contains(out, markRule) || strings.Contains(out, tailscaleSNATMark) {
			goto fw4
		}
	}
	_ = runOK("nft", "add", "table", "ip", "gw_mangle")
	_ = runOK("nft", "add", "chain", "ip", "gw_mangle", "forward",
		"{", "type", "filter", "hook", "forward", "priority", "mangle", ";", "policy", "accept", ";", "}")
	_ = runOK("nft", "add", "rule", "ip", "gw_mangle", "forward",
		"iifname", "wg0", "oifname", "tailscale0", "meta", "mark", "set", tailscaleSNATMark)

fw4:
	if out, err := run("nft", "list", "chain", "inet", "fw4", "forward"); err == nil {
		if strings.Contains(out, tailscaleSNATMark) {
			return
		}
	}
	_ = runOK("nft", "insert", "rule", "inet", "fw4", "forward",
		"iifname", "wg0", "oifname", "tailscale0", "meta", "mark", "set", tailscaleSNATMark, "accept")
}

func setExitNode(exitNodeID, netIface string) error {
	if strings.TrimSpace(exitNodeID) == "" {
		return clearExitNode(netIface)
	}
	vmIP, err := vmLANIP()
	if err != nil {
		return err
	}
	wgIP, err := wgGatewayIP("wg0")
	if err != nil {
		return err
	}
	subnet := wgSubnet("wg0")

	ipRule("35", "to", subnet, "lookup", "main")
	ipRule("40", "from", wgIP+"/32", "lookup", "main")
	ipRule("50", "from", vmIP+"/32", "lookup", "main")
	removeCustomTailscaleMasquerade()
	ensureWgTailscaleForwardMark()

	if err := runOK("tailscale", "set",
		"--exit-node="+exitNodeID,
		"--exit-node-allow-lan-access=false",
		"--netfilter-mode=on"); err != nil {
		return err
	}
	_ = runOK("tailscale", "set", "--advertise-routes=")
	removeCustomTailscaleMasquerade()
	ensureWgTailscaleForwardMark()
	_ = os.MkdirAll("/opt/gateway-agent", 0o700)
	return os.WriteFile("/opt/gateway-agent/exit-node.env", []byte("EXIT_NODE_ID="+exitNodeID+"\n"), 0o600)
}

func clearExitNode(netIface string) error {
	_ = netIface
	if err := runOK("tailscale", "set", "--exit-node=", "--netfilter-mode=off"); err != nil {
		return err
	}
	_ = os.Remove("/opt/gateway-agent/exit-node.env")
	return nil
}

func main() {
	cfg := loadConfig()
	if cfg.Token == "" {
		fmt.Fprintln(os.Stderr, "AGENT_TOKEN required")
		os.Exit(1)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/register", func(w http.ResponseWriter, r *http.Request) {
		if !auth(cfg, r) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var body struct {
			GatewayName string `json:"gateway_name"`
		}
		_ = readJSON(r, &body)
		writeJSON(w, http.StatusOK, map[string]string{"status": "registered", "gateway_name": body.GatewayName})
	})
	mux.HandleFunc("/v1/health", func(w http.ResponseWriter, r *http.Request) {
		if !auth(cfg, r) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"wg_online": wgOnline(cfg.WGInterface), "tailscale_online": tailscaleOnline(),
			"nft_running": nftRunning(), "exit_node_configured": exitNodeConfigured(),
		})
	})
	mux.HandleFunc("/v1/peers", func(w http.ResponseWriter, r *http.Request) {
		if !auth(cfg, r) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		switch r.Method {
		case http.MethodGet:
			peers, err := listPeers(cfg.WGInterface)
			if err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
			writeJSON(w, http.StatusOK, peers)
		case http.MethodPost:
			var body struct {
				PublicKey  string `json:"public_key"`
				AllowedIPs string `json:"allowed_ips"`
			}
			if err := readJSON(r, &body); err != nil {
				http.Error(w, err.Error(), http.StatusBadRequest)
				return
			}
			if err := runOK("wg", "set", cfg.WGInterface, "peer", body.PublicKey, "allowed-ips", body.AllowedIPs); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
			writeJSON(w, http.StatusOK, map[string]string{"status": "created", "public_key": body.PublicKey})
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	})
	mux.HandleFunc("/v1/wg/config", func(w http.ResponseWriter, r *http.Request) {
		if !auth(cfg, r) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		out, err := run("wg", "showconf", cfg.WGInterface)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"config": out})
	})
	mux.HandleFunc("/v1/tailscale/exit-node", func(w http.ResponseWriter, r *http.Request) {
		if !auth(cfg, r) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var body struct {
			ExitNodeID string `json:"exit_node_id"`
		}
		if err := readJSON(r, &body); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if err := setExitNode(body.ExitNodeID, cfg.NetInterface); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		status := "updated"
		if strings.TrimSpace(body.ExitNodeID) == "" {
			status = "cleared"
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": status, "exit_node_id": body.ExitNodeID})
	})
	mux.HandleFunc("/v1/peers/", func(w http.ResponseWriter, r *http.Request) {
		if !auth(cfg, r) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		path := strings.TrimPrefix(r.URL.Path, "/v1/peers/")
		parts := strings.Split(path, "/")
		if len(parts) == 0 || parts[0] == "" {
			http.NotFound(w, r)
			return
		}
		pubkey := parts[0]
		if len(parts) == 1 && r.Method == http.MethodDelete {
			if err := runOK("wg", "set", cfg.WGInterface, "peer", pubkey, "remove"); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
			writeJSON(w, http.StatusOK, map[string]string{"status": "deleted", "public_key": pubkey})
			return
		}
		if len(parts) == 2 {
			ip := r.URL.Query().Get("allowed_ip")
			if ip == "" {
				http.Error(w, "allowed_ip required", http.StatusBadRequest)
				return
			}
			ip = strings.Split(ip, "/")[0]
			var err error
			switch parts[1] {
			case "suspend":
				err = suspendPeerIP(cfg.NFTTable, ip)
			case "resume":
				err = resumePeerIP(cfg.NFTTable, ip)
			default:
				http.NotFound(w, r)
				return
			}
			if err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
			writeJSON(w, http.StatusOK, map[string]string{"status": parts[1] + "ed", "public_key": pubkey})
			return
		}
		http.NotFound(w, r)
	})

	addr := cfg.ListenHost + ":" + cfg.ListenPort
	fmt.Printf("gateway-agent listening on %s\n", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
