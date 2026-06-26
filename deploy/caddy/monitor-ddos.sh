#!/bin/bash
# ========================================================
# REAL-TIME DDoS MONITORING DASHBOARD
# Live updates every 1-2 seconds
# ========================================================

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Clear screen function
clear_and_show() {
    clear
    echo -e "${CYAN}=========================================${NC}"
    echo -e "${CYAN}REAL-TIME DDoS MONITORING DASHBOARD${NC}"
    echo -e "${CYAN}Updated: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo -e "${CYAN}=========================================${NC}"
    echo ""
}

# Function to get connection stats
show_connections() {
    echo -e "${BLUE}[1] ACTIVE CONNECTIONS BY IP (Top 15)${NC}"
    echo "IP Address          | Count | Status"
    echo "==========================================|====="
    sudo netstat -an 2>/dev/null | grep ESTABLISHED | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -15 | awk '{printf "%-20s | %5d\n", $2, $1}' || echo "No connections"
    echo ""
}

# Function to get port stats
show_port_stats() {
    echo -e "${BLUE}[2] TRAFFIC BY PORT${NC}"
    echo "Port | Connections | Type"
    echo "============================"
    echo -n "80   | "
    sudo netstat -an 2>/dev/null | grep ":80 " | wc -l
    echo " | HTTP"
    echo -n "443  | "
    sudo netstat -an 2>/dev/null | grep ":443 " | wc -l
    echo " | HTTPS"
    echo -n "22   | "
    sudo netstat -an 2>/dev/null | grep ":22 " | wc -l
    echo " | SSH"
    echo ""
}

# Function to get resource stats
show_resources() {
    echo -e "${BLUE}[3] SYSTEM RESOURCES${NC}"
    
    # CPU Usage
    CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{printf("%.1f", 100 - $1)}')
    
    # Memory
    MEM_DATA=$(free | grep Mem)
    MEM_USED=$(echo $MEM_DATA | awk '{printf("%.1f", ($3/$2)*100)}')
    MEM_TOTAL=$(echo $MEM_DATA | awk '{print $2}')
    MEM_USED_MB=$(echo $MEM_DATA | awk '{print $3}')
    
    # Network
    RX_BYTES=$(cat /proc/net/dev | grep "eth0" | awk '{print $2}')
    TX_BYTES=$(cat /proc/net/dev | grep "eth0" | awk '{print $10}')
    
    echo "CPU Usage: ${CPU_USAGE}%"
    echo "Memory: ${MEM_USED}% (${MEM_USED_MB}MB / ${MEM_TOTAL}MB)"
    echo "Network RX: ${RX_BYTES} bytes"
    echo "Network TX: ${TX_BYTES} bytes"
    echo ""
}

# Function to show connection states
show_connection_states() {
    echo -e "${BLUE}[4] CONNECTION STATES${NC}"
    
    ESTABLISHED=$(sudo netstat -an 2>/dev/null | grep ESTABLISHED | wc -l)
    LISTEN=$(sudo netstat -an 2>/dev/null | grep LISTEN | wc -l)
    TIME_WAIT=$(sudo netstat -an 2>/dev/null | grep TIME_WAIT | wc -l)
    CLOSE_WAIT=$(sudo netstat -an 2>/dev/null | grep CLOSE_WAIT | wc -l)
    SYN_RECV=$(sudo netstat -an 2>/dev/null | grep SYN_RECV | wc -l)
    
    echo "ESTABLISHED: ${ESTABLISHED}"
    echo "LISTEN: ${LISTEN}"
    echo "TIME_WAIT: ${TIME_WAIT}"
    echo "CLOSE_WAIT: ${CLOSE_WAIT}"
    echo "SYN_RECV: ${SYN_RECV}"
    
    if [ "$ESTABLISHED" -gt 500 ]; then
        echo -e "${RED}⚠️  WARNING: HIGH ESTABLISHED CONNECTIONS!${NC}"
    fi
    
    if [ "$SYN_RECV" -gt 100 ]; then
        echo -e "${RED}⚠️  WARNING: HIGH SYN_RECV (Possible SYN Flood!)${NC}"
    fi
    
    echo ""
}

# Function to show dropped packets
show_dropped_packets() {
    echo -e "${BLUE}[5] IPTables ACTIVITY (Last 5 min)${NC}"
    
    # Get IPv4 drops
    IPV4_DROPS=$(sudo iptables -L INPUT -n -v 2>/dev/null | grep "DROP" | awk '{sum += $2} END {print sum}')
    
    # Get IPv6 drops
    IPV6_DROPS=$(sudo ip6tables -L INPUT -n -v 2>/dev/null | grep "DROP" | awk '{sum += $2} END {print sum}')
    
    TOTAL_DROPS=$((${IPV4_DROPS:-0} + ${IPV6_DROPS:-0}))
    
    echo "Total Dropped Packets: ${TOTAL_DROPS}"
    echo "IPv4 Drops: ${IPV4_DROPS:-0}"
    echo "IPv6 Drops: ${IPV6_DROPS:-0}"
    
    if [ "$TOTAL_DROPS" -gt 1000 ]; then
        echo -e "${RED}⚠️  WARNING: HIGH DROP RATE!${NC}"
    fi
    
    echo ""
}

# Function to show suspicious IPs
show_suspicious_ips() {
    echo -e "${BLUE}[6] SUSPICIOUS IPs (Multiple Connections)${NC}"
    
    sudo netstat -an 2>/dev/null | grep ESTABLISHED | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | awk '$1 > 50 {printf "%-20s | %5d connections\n", $2, $1}' | head -10 || echo "No suspicious activity"
    echo ""
}

# Function to show recent Caddy logs
show_caddy_logs() {
    echo -e "${BLUE}[7] RECENT CADDY LOGS (Last 5)${NC}"
    sudo journalctl -u caddy -n 5 --no-pager 2>/dev/null | tail -5 | while read line; do
        if [[ $line == *"error"* ]] || [[ $line == *"drop"* ]]; then
            echo -e "${RED}$line${NC}"
        else
            echo "$line"
        fi
    done || echo "No logs"
    echo ""
}

# Function to show alerts
show_alerts() {
    echo -e "${BLUE}[8] ALERTS & STATUS${NC}"
    
    ESTABLISHED=$(sudo netstat -an 2>/dev/null | grep ESTABLISHED | wc -l)
    
    if [ "$ESTABLISHED" -lt 10 ]; then
        echo -e "${GREEN}✓ Normal traffic levels${NC}"
    elif [ "$ESTABLISHED" -lt 100 ]; then
        echo -e "${YELLOW}⚠️  Moderate traffic${NC}"
    elif [ "$ESTABLISHED" -lt 500 ]; then
        echo -e "${YELLOW}⚠️  High traffic detected${NC}"
    else
        echo -e "${RED}🔴 POTENTIAL DDoS ATTACK!${NC}"
    fi
    
    echo ""
}

# Function to show help
show_help() {
    echo -e "${CYAN}KEYBOARD COMMANDS:${NC}"
    echo "  q - Quit"
    echo "  h - Help"
    echo "  1 - Show only connections"
    echo "  2 - Show only ports"
    echo "  3 - Show only resources"
    echo "  b - Block top attacking IP"
    echo "  Spacebar - Refresh now"
    echo ""
}

# Main monitoring loop
main_loop() {
    while true; do
        clear_and_show
        
        show_connections
        show_port_stats
        show_resources
        show_connection_states
        show_dropped_packets
        show_suspicious_ips
        show_caddy_logs
        show_alerts
        show_help
        
        echo "Refreshing in 2 seconds... (Press Ctrl+C to exit, 'h' for help)"
        
        # Check for user input with timeout
        read -t 2 -n 1 input
        
        case $input in
            q|Q)
                echo "Exiting..."
                exit 0
                ;;
            h|H)
                show_help
                read -t 3
                ;;
            b|B)
                TOP_IP=$(sudo netstat -an 2>/dev/null | grep ESTABLISHED | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')
                if [ ! -z "$TOP_IP" ]; then
                    echo -e "${RED}Blocking IP: $TOP_IP${NC}"
                    sudo iptables -A INPUT -s $TOP_IP -j DROP
                    echo "IP blocked! Saving..."
                    sudo iptables-save | sudo tee /etc/iptables/rules.v4 > /dev/null
                    echo "Done!"
                    read -t 2
                fi
                ;;
        esac
    done
}

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo bash $0"
    exit 1
fi

# Start monitoring
main_loop