document.addEventListener("DOMContentLoaded", () => {
    // 1. Initial State
    let selectedStore = "STORE_BLR_001";
    let refreshInterval = null;

    const storeSelector = document.getElementById("storeSelector");
    const refreshBtn = document.getElementById("refreshBtn");

    // 2. Event Listeners
    storeSelector.addEventListener("change", (e) => {
        selectedStore = e.target.value;
        fetchDashboardData();
    });

    refreshBtn.addEventListener("click", () => {
        fetchDashboardData();
        // Spin the icon
        const icon = refreshBtn.querySelector("i");
        if (icon) {
            icon.style.transform = "rotate(360deg)";
            setTimeout(() => {
                icon.style.transform = "none";
            }, 500);
        }
    });

    // 3. Main Data Fetch Router
    function fetchDashboardData() {
        updateKPIs();
        updateFunnel();
        updateHeatmap();
        updateAnomalies();
        updateFeedStatus();
    }

    // 4. Update KPI Metrics
    async function updateKPIs() {
        try {
            const res = await fetch(`/stores/${selectedStore}/metrics`);
            if (!res.ok) throw new Error("Metrics fetch error");
            const data = await res.json();

            document.getElementById("kpiVisitors").textContent = data.unique_visitors;
            document.getElementById("kpiConversion").textContent = `${data.conversion_rate}%`;
            
            const queueVal = document.getElementById("kpiQueue");
            const queueStatus = document.getElementById("kpiQueueStatus");
            queueVal.textContent = data.queue_depth;

            // Highlight queue card if depth is high
            if (data.queue_depth > 8) {
                queueVal.style.color = "var(--red)";
                queueStatus.textContent = "CRITICAL queue spike";
                queueStatus.style.color = "var(--red)";
            } else if (data.queue_depth > 5) {
                queueVal.style.color = "var(--yellow)";
                queueStatus.textContent = "Elevated queue line";
                queueStatus.style.color = "var(--yellow)";
            } else {
                queueVal.style.color = "var(--text-main)";
                queueStatus.textContent = "Normal checkout queue";
                queueStatus.style.color = "var(--text-muted)";
            }

            document.getElementById("kpiAbandonment").textContent = `${data.abandonment_rate}%`;
        } catch (e) {
            console.error("Error updating KPIs:", e);
        }
    }

    // 5. Update Conversion Funnel
    async function updateFunnel() {
        const container = document.getElementById("funnelContainer");
        try {
            const res = await fetch(`/stores/${selectedStore}/funnel`);
            if (!res.ok) throw new Error("Funnel fetch error");
            const data = await res.json();

            if (!data.funnel || data.funnel.length === 0) {
                container.innerHTML = `<div class="loader">No funnel data available for this store.</div>`;
                return;
            }

            // Find maximum count for scaling bar width
            const baseCount = data.funnel[0].count || 1;
            
            let html = "";
            data.funnel.forEach((stage) => {
                const widthPct = baseCount > 0 ? (stage.count / baseCount) * 100 : 0;
                const dropoffText = stage.stage_name !== "Entry" ? `-${stage.drop_off_pct}%` : "Base";
                const dropoffClass = stage.drop_off_pct > 30 ? "funnel-dropoff active" : "funnel-dropoff";
                
                html += `
                    <div class="funnel-step">
                        <div class="funnel-label">${stage.stage_name}</div>
                        <div class="funnel-bar-wrapper">
                            <div class="funnel-bar" style="width: ${widthPct}%"></div>
                            <span class="funnel-bar-text">${stage.count} shoppers</span>
                        </div>
                        <div class="${dropoffClass}">${dropoffText}</div>
                    </div>
                `;
            });
            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = `<div class="loader">Error loading funnel metrics.</div>`;
            console.error(e);
        }
    }

    // 6. Update Zone Heatmap
    async function updateHeatmap() {
        const container = document.getElementById("heatmapContainer");
        const confBadge = document.getElementById("dataConfidenceBadge");
        try {
            const res = await fetch(`/stores/${selectedStore}/heatmap`);
            if (!res.ok) throw new Error("Heatmap fetch error");
            const data = await res.json();

            // Set data confidence badge color
            if (data.data_confidence === "HIGH") {
                confBadge.textContent = "HIGH CONFIDENCE";
                confBadge.className = "badge green";
            } else {
                confBadge.textContent = "LOW DATA CONFIDENCE";
                confBadge.className = "badge yellow";
            }

            if (!data.heatmap || data.heatmap.length === 0) {
                container.innerHTML = `<div class="loader">No shopper dwell data recorded yet.</div>`;
                return;
            }

            let html = "";
            data.heatmap.forEach((item) => {
                html += `
                    <div class="heatmap-row">
                        <div class="heatmap-zone-label">${item.zone_id}</div>
                        <div class="heatmap-track-wrapper">
                            <div class="heatmap-track" style="width: ${item.intensity}%"></div>
                            <span class="heatmap-track-text">${item.visit_count} visits</span>
                        </div>
                        <div class="heatmap-detail">${item.avg_dwell_sec}s avg dwell</div>
                    </div>
                `;
            });
            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = `<div class="loader">Error loading engagement heatmap.</div>`;
            console.error(e);
        }
    }

    // 7. Update Anomalies Feed
    async function updateAnomalies() {
        const container = document.getElementById("anomalyList");
        try {
            const res = await fetch(`/stores/${selectedStore}/anomalies`);
            if (!res.ok) throw new Error("Anomalies fetch error");
            const list = await res.json();

            if (!list || list.length === 0) {
                container.innerHTML = `
                    <div class="no-anomalies">
                        No active anomalies detected. Operations running smoothly.
                    </div>
                `;
                return;
            }

            let html = "";
            list.forEach((anomaly) => {
                let icon = "alert-triangle";
                if (anomaly.severity === "CRITICAL") icon = "alert-circle";
                else if (anomaly.severity === "INFO") icon = "info";
                
                html += `
                    <div class="anomaly-item ${anomaly.severity}">
                        <div class="anomaly-badge ${anomaly.severity}">${anomaly.severity}</div>
                        <div class="anomaly-body">
                            <span class="anomaly-desc">${anomaly.details}</span>
                            <span class="anomaly-action"><strong>Recommended Action:</strong> ${anomaly.suggested_action}</span>
                            <span class="anomaly-time">${anomaly.anomaly_type} • timestamp: ${anomaly.timestamp}</span>
                        </div>
                    </div>
                `;
            });
            container.innerHTML = html;
            
            // Re-render Lucide icons injected in anomalies
            if (window.lucide) {
                window.lucide.createIcons();
            }
        } catch (e) {
            container.innerHTML = `<div class="loader">Error querying operational anomalies.</div>`;
            console.error(e);
        }
    }

    // 8. Update System Feed Status
    async function updateFeedStatus() {
        const container = document.getElementById("feedStatusList");
        try {
            const res = await fetch("/health");
            if (!res.ok) throw new Error("Health check query error");
            const data = await res.json();

            if (!data.store_feeds || Object.keys(data.store_feeds).length === 0) {
                container.innerHTML = `<div class="loader">No store camera streams registered.</div>`;
                return;
            }

            let html = "";
            Object.keys(data.store_feeds).forEach((storeId) => {
                const feed = data.store_feeds[storeId];
                let timeText = "No feed received";
                let badgeClass = "status-pill no-feed";
                
                if (feed.last_event_timestamp) {
                    timeText = `Last Event: ${feed.last_event_timestamp}`;
                }
                
                html += `
                    <div class="status-item">
                        <div class="status-info">
                            <span class="status-store-code">${storeId}</span>
                            <span class="status-time-ago">${timeText}</span>
                        </div>
                        <span class="status-pill ${feed.status}">${feed.status}</span>
                    </div>
                `;
            });
            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = `<div class="loader">Error reading camera feeds.</div>`;
            console.error(e);
        }
    }

    // 9. Initial Load and Setup Polling Loop
    fetchDashboardData();
    
    // Poll endpoints every 5 seconds for real-time visual simulation
    refreshInterval = setInterval(fetchDashboardData, 5000);
    
    // Initialize initial icons
    if (window.lucide) {
        window.lucide.createIcons();
    }
});
