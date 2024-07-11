// Set new default font family and font color to mimic Bootstrap's default styling
Chart.defaults.global.defaultFontFamily = 'Nunito', '-apple-system,system-ui,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif';
Chart.defaults.global.defaultFontColor = '#858796';

function updateChart() {
    const filter = document.getElementById("filter").value;
    fetch(`/api/piechart-data?filter=${filter}`)
        .then(response => response.json())
        .then(data => {
            var ctx = document.getElementById("myPieChart");
            if ('message' in data) {
                document.getElementById("chartMessage").textContent = data.message;
                ctx.style.display = 'none'; // Hide the chart canvas
            } else {
                var myPieChart = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: ["Pelanggaran", "Taat Aturan"],
                        datasets: [{
                            data: [data.pelanggaran, data.taat],
                            backgroundColor: ['#e74a3b', '#1cc88a'],
                            hoverBackgroundColor: ['#c0392b', '#17a673'],
                            hoverBorderColor: "rgba(234, 236, 244, 1)",
                        }],
                    },
                    options: {
                        maintainAspectRatio: false,
                        tooltips: {
                            backgroundColor: "rgb(255,255,255)",
                            bodyFontColor: "#858796",
                            borderColor: '#dddfeb',
                            borderWidth: 1,
                            xPadding: 15,
                            yPadding: 15,
                            displayColors: false,
                            caretPadding: 10,
                        },
                        legend: {
                            display: false
                        },
                        cutoutPercentage: 80,
                    },
                });
                document.getElementById("chartMessage").textContent = ''; // Clear any previous message
                ctx.style.display = 'block'; // Show the chart canvas
            }
        });
}

// Initial chart load
document.addEventListener("DOMContentLoaded", function() {
    updateChart();
});