#!/bin/bash
# ========================================================
# REAL-TIME HTTP TRAFFIC TRACKING
# Track GET, POST, PUT, DELETE, PATCH requests
# ========================================================

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

clear_screen() {
    clear
    echo -e "${CYAN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║   REAL-TIME HTTP TRAFFIC TRACKING         ║${NC}"
    echo -e "${CYAN}║   $(date '+%Y-%m-%d %H:%M:%S')                      ║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════╝${NC}"
    echo ""
}

# Function to show HTTP method counts
show_method_stats() {
    echo -e "${BLUE}[1] HTTP METHODS (Last 100 requests)${NC}"
    echo "Method  | Count | Percentage"
    echo "================================"
    
    TOTAL=$(sudo journalctl -u caddy -n 1000 --no-pager 2>/dev/null | grep -oE '"method":"[A-Z]+"' | wc -l)
    
    for method in GET POST PUT DELETE PATCH HEAD OPTIONS; do
        COUNT=$(sudo journalctl -u caddy -n 1000 --no-pager 2>/dev/null | grep -oE '"method":"'$method'"' | wc -l)
        if [ "$COUNT" -gt 0 ] && [ "$TOTAL" -gt 0 ]; then
            PERCENT=$((COUNT * 100 / TOTAL))
            printf "%-7s | %5d | %3d%%\n" "$method" "$COUNT" "$PERCENT"
        fi
    done
    echo ""
}

# Function to show endpoint stats
show_endpoint_stats() {
    echo -e "${BLUE}[2] TOP ENDPOINTS (Last 1000 requests)${NC}"
    echo "Endpoint                          | Method | Count"
    echo "======================================================"
    
    sudo journalctl -u caddy -n 1000 --no-pager 2>/dev/null | \
        grep -oE '"uri":"[^"]+"|"method":"[A-Z]+"' | \
        paste -d' ' - - | \
        sed 's/"uri":"\([^"]*\)".*"method":"\([^"]*\)".*/\2 \1/' | \
        awk '{uri=$2; method=$1; print uri " " method}' | \
        sort | uniq -c | sort -rn | head -15 | \
        awk '{printf "%-33s | %6s | %5d\n", $3, $2, $1}'
    
    echo ""
}

# Function to show status codes
show_status_codes() {
    echo -e "${BLUE}[3] HTTP STATUS CODES (Last 500 requests)${NC}"
    echo "Status | Count | Type"
    echo "============================"
    
    sudo journalctl -u caddy -n 500 --no-pager 2>/dev/null | \
        grep -oE '"status":[0-9]+' | \
        sed 's/"status"://' | \
        sort | uniq -c | sort -rn | \
        while read count status; do
            case $status in
                2*) TYPE="Success" ;;
                3*) TYPE="Redirect" ;;
                4*) TYPE="Client Error" ;;
                5*) TYPE="Server Error" ;;
                *) TYPE="Unknown" ;;
            esac
            printf "%6s | %5d | %s\n" "$status" "$count" "$TYPE"
        done
    echo ""
}

# Function to show requests by IP
show_requests_by_ip() {
    echo -e "${BLUE}[4] REQUESTS BY IP (Top 10)${NC}"
    echo "IP Address          | Count | Last Method"
    echo "=============================================="
    
    sudo journalctl -u caddy -n 500 --no-pager 2>/dev/null | \
        grep -oE '"remote_ip":"[^"]+"' | \
        sed 's/"remote_ip":"//' | sed 's/".*//' | \
        sort | uniq -c | sort -rn | head -10 | \
        while read count ip; do
            # Get last method used by this IP
            LAST_METHOD=$(sudo journalctl -u caddy -n 500 --no-pager 2>/dev/null | \
                grep "\"remote_ip\":\"$ip\"" | \
                tail -1 | \
                grep -oE '"method":"[^"]+"' | sed 's/"method":"//' | sed 's/".*//')
            printf "%-19s | %5d | %s\n" "$ip" "$count" "$LAST_METHOD"
        done
    echo ""
}

# Function to show requests by domain
show_requests_by_domain() {
    echo -e "${BLUE}[5] REQUESTS BY DOMAIN (Last 500)${NC}"
    echo "Domain                    | GET | POST | PUT | DELETE | PATCH | Total"
    echo "====================================================================="
    
    DOMAINS=$(sudo journalctl -u caddy -n 500 --no-pager 2>/dev/null | \
        grep -oE '"host":"[^"]+"' | sed 's/"host":"//' | sed 's/".*//' | sort -u)
    
    for domain in $DOMAINS; do
        DOMAIN_LOGS=$(sudo journalctl -u caddy -n 500 --no-pager 2>/dev/null | grep "\"host\":\"$domain\"")
        
        GET=$(echo "$DOMAIN_LOGS" | grep '"method":"GET"' | wc -l)
        POST=$(echo "$DOMAIN_LOGS" | grep '"method":"POST"' | wc -l)
        PUT=$(echo "$DOMAIN_LOGS" | grep '"method":"PUT"' | wc -l)
        DELETE=$(echo "$DOMAIN_LOGS" | grep '"method":"DELETE"' | wc -l)
        PATCH=$(echo "$DOMAIN_LOGS" | grep '"method":"PATCH"' | wc -l)
        TOTAL=$(echo "$DOMAIN_LOGS" | wc -l)
        
        printf "%-25s | %3d | %4d | %3d | %6d | %5d | %5d\n" "$domain" "$GET" "$POST" "$PUT" "$DELETE" "$PATCH" "$TOTAL"
    done
    echo ""
}

# Function to show slow requests
show_slow_requests() {
    echo -e "${BLUE}[6] SLOW REQUESTS (>1000ms) - Last 50${NC}"
    echo "Duration | Method | Endpoint                | Status"
    echo "=========================================================="
    
    sudo journalctl -u caddy -n 500 --no-pager 2>/dev/null | \
        grep -oE '"duration":"[0-9]+(ms|us|s)".*"method":"[A-Z]+".*"uri":"[^"]+".*"status":[0-9]+' | \
        sed 's/"duration":"\([^"]*\)".*/\1/' | \
        paste -d' ' - - | \
        awk '{
            duration=$1
            gsub(/ms|us|s/, "", duration)
            if (duration > 1000) print $0
        }' | head -10 | \
        while read line; do
            DURATION=$(echo "$line" | sed 's/"duration":"\([^"]*\)".*/\1/')
            METHOD=$(echo "$line" | grep -oE '"method":"[^"]+"' | sed 's/"method":"//' | sed 's/".*//')
            ENDPOINT=$(echo "$line" | grep -oE '"uri":"[^"]+"' | sed 's/"uri":"//' | sed 's/".*//' | cut -c1-23)
            STATUS=$(echo "$line" | grep -oE '"status":[0-9]+' | sed 's/"status"://')
            printf "%7s | %6s | %-23s | %6s\n" "$DURATION" "$METHOD" "$ENDPOINT" "$STATUS"
        done
    echo ""
}

# Function to show error requests
show_error_requests() {
    echo -e "${BLUE}[7] ERROR REQUESTS (4xx, 5xx) - Last 20${NC}"
    echo "Status | Method | Endpoint                | IP Address"
    echo "========================================================"
    
    sudo journalctl -u caddy -n 500 --no-pager 2>/dev/null | \
        grep -E '"status":[45][0-9]{2}' | \
        tail -20 | \
        while read line; do
            STATUS=$(echo "$line" | grep -oE '"status":[0-9]+' | sed 's/"status"://')
            METHOD=$(echo "$line" | grep -oE '"method":"[^"]+"' | sed 's/"method":"//' | sed 's/".*//')
            ENDPOINT=$(echo "$line" | grep -oE '"uri":"[^"]+"' | sed 's/"uri":"//' | sed 's/".*//' | cut -c1-23)
            IP=$(echo "$line" | grep -oE '"remote_ip":"[^"]+"' | sed 's/"remote_ip":"//' | sed 's/".*//')
            
            if [ "$STATUS" -ge 500 ]; then
                COLOR=$RED
            else
                COLOR=$YELLOW
            fi
            printf "${COLOR}%6s${NC} | %6s | %-23s | %s\n" "$STATUS" "$METHOD" "$ENDPOINT" "$IP"
        done
    echo ""
}

# Function to show real-time traffic
show_realtime_traffic() {
    echo -e "${BLUE}[8] REAL-TIME TRAFFIC (Last 10 seconds)${NC}"
    echo "Timestamp            | Method | Domain              | Endpoint        | Status | Duration"
    echo "=========================================================================================="
    
    CUTOFF_TIME=$(($(date +%s) - 10))
    
    sudo journalctl -u caddy --since "10 seconds ago" --no-pager 2>/dev/null | \
        grep -oE '"ts":[0-9.]+.*"method":"[A-Z]+".*"host":"[^"]+".*"uri":"[^"]+".*"status":[0-9]+.*"duration":"[^"]+"' | \
        tail -10 | \
        while read line; do
            TIMESTAMP=$(echo "$line" | grep -oE '"ts":[0-9.]+' | sed 's/"ts"://' | xargs -I {} date -d @{} '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "N/A")
            METHOD=$(echo "$line" | grep -oE '"method":"[^"]+"' | sed 's/"method":"//' | sed 's/".*//')
            HOST=$(echo "$line" | grep -oE '"host":"[^"]+"' | sed 's/"host":"//' | sed 's/".*//' | cut -c1-19)
            URI=$(echo "$line" | grep -oE '"uri":"[^"]+"' | sed 's/"uri":"//' | sed 's/".*//' | cut -c1-15)
            STATUS=$(echo "$line" | grep -oE '"status":[0-9]+' | sed 's/"status"://')
            DURATION=$(echo "$line" | grep -oE '"duration":"[^"]+"' | sed 's/"duration":"//' | sed 's/".*//')
            
            if [ "$STATUS" -ge 500 ]; then
                COLOR=$RED
            elif [ "$STATUS" -ge 400 ]; then
                COLOR=$YELLOW
            elif [ "$STATUS" -ge 300 ]; then
                COLOR=$MAGENTA
            else
                COLOR=$GREEN
            fi
            printf "%-19s | %6s | %-19s | %-15s | ${COLOR}%6s${NC} | %s\n" "$TIMESTAMP" "$METHOD" "$HOST" "$URI" "$STATUS" "$DURATION"
        done
    echo ""
}

# Function to show summary
show_summary() {
    echo -e "${BLUE}[9] SUMMARY${NC}"
    
    TOTAL_REQUESTS=$(sudo journalctl -u caddy -n 1000 --no-pager 2>/dev/null | grep -c '"method"')
    SUCCESS=$(sudo journalctl -u caddy -n 1000 --no-pager 2>/dev/null | grep -c '"status":2')
    ERRORS=$(sudo journalctl -u caddy -n 1000 --no-pager 2>/dev/null | grep -cE '"status":[45]')
    
    echo "Total Requests (last 1000): $TOTAL_REQUESTS"
    echo -e "${GREEN}✓ Success (2xx): $SUCCESS${NC}"
    echo -e "${RED}✗ Errors (4xx, 5xx): $ERRORS${NC}"
    echo ""
}

# Main loop
main_loop() {
    while true; do
        clear_screen
        show_method_stats
        show_endpoint_stats
        show_status_codes
        show_requests_by_ip
        show_requests_by_domain
        show_slow_requests
        show_error_requests
        show_realtime_traffic
        show_summary
        
        echo -e "${CYAN}Press Ctrl+C to exit | Refreshing in 3 seconds...${NC}"
        sleep 3
    done
}

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo bash $0"
    exit 1
fi

# Start monitoring
main_loop