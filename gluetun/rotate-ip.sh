#!/bin/sh
# Xoay IP VPN định kỳ — chống bị chặn vì "too many requests" từ một IP.
#
# gluetun KHÔNG tự xoay IP: nó nối một server rồi giữ nguyên. Cách duy nhất được
# hỗ trợ chính thức là gọi control server stop→start; mỗi lần nối lại nó bốc một
# server khác trong nhóm SERVER_COUNTRIES.
#
# Script để riêng (không nhúng vào YAML) vì trong compose, "$" phải viết "$$" —
# rất dễ sai và không kiểm được cú pháp. Ở đây là shell thuần, `sh -n` kiểm được.
set -u

G="${GLUETUN_URL:-http://gluetun:8000}"
MINUTES="${ROTATE_MINUTES:-15}"

# Lấy IP public hiện tại qua control server. Rỗng = VPN chưa lên.
current_ip() {
	curl -s -m 10 "$G/v1/publicip/ip" 2>/dev/null |
		sed -n 's/.*"public_ip":"\([^"]*\)".*/\1/p'
}

# Chờ VPN lên lần đầu rồi mới vào vòng lặp — tránh xoay khi chưa hề kết nối.
while [ -z "$(current_ip)" ]; do
	sleep 5
done
echo "[rotator] VPN san sang | IP=$(current_ip) | chu ky=${MINUTES} phut"

while true; do
	sleep $((MINUTES * 60))

	before="$(current_ip)"
	curl -s -m 10 -X PUT -d '{"status":"stopped"}' "$G/v1/vpn/status" >/dev/null 2>&1
	sleep 3
	curl -s -m 10 -X PUT -d '{"status":"running"}' "$G/v1/vpn/status" >/dev/null 2>&1

	# Chờ IP trở lại, tối đa ~60s, rồi mới kết luận.
	i=0
	while [ -z "$(current_ip)" ] && [ "$i" -lt 12 ]; do
		sleep 5
		i=$((i + 1))
	done

	after="$(current_ip)"
	if [ -z "$after" ]; then
		echo "[rotator] CANH BAO: xoay xong nhung chua lay duoc IP — VPN chua len lai?"
	elif [ "$after" = "$before" ]; then
		echo "[rotator] da noi lai nhung trung server cu ($after) — binh thuong khi nhom server hep"
	else
		echo "[rotator] IP doi: $before -> $after"
	fi
done
