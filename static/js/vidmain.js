const defaultZone = {
    x1: 440,
    y1: 290,
    x2: 490,
    y2: 300,
    x3: 410,
    y3: 380,
    x4: 330,
    y4: 360
};

function updateZone() {
    let zone = [
        [parseInt(document.getElementById('x1').value), parseInt(document.getElementById('y1').value)],
        [parseInt(document.getElementById('x2').value), parseInt(document.getElementById('y2').value)],
        [parseInt(document.getElementById('x3').value), parseInt(document.getElementById('y3').value)],
        [parseInt(document.getElementById('x4').value), parseInt(document.getElementById('y4').value)]
    ];

    fetch('/set_zone', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ zone: zone })
    });
}

document.querySelectorAll('.slider').forEach(slider => {
    slider.addEventListener('input', updateZone);
});

document.getElementById('videoType').addEventListener('change', function() {
    let videoType = this.value;
    document.getElementById('ipInput').style.display = (videoType === 'ip') ? 'block' : 'none';
    document.getElementById('fileInput').style.display = (videoType === 'file') ? 'block' : 'none';
});

document.getElementById('videoForm').onsubmit = function(e) {
    e.preventDefault();
    let formData = new FormData(this);

    // Stop the current video stream
    let videoStream = document.getElementById('videoStream');
    videoStream.src = '';

    fetch('/upload_video', {
        method: 'POST',
        body: formData
    }).then(response => response.json())
      .then(data => {
          // Enable the toggle button
          document.getElementById('toggleButton').disabled = false;

          // Start the new video stream
          setTimeout(() => {
              videoStream.src = '/video_feed?video_source=' + encodeURIComponent(data.video_source);
          }, 500); // Adding a small delay to ensure the reset takes effect
      });
};

document.getElementById('toggleButton').addEventListener('click', function() {
    fetch('/toggle_video', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            this.textContent = data.paused ? 'Resume Video' : 'Pause Video';
        });
});

document.getElementById('resetButton').addEventListener('click', function() {
    fetch('/reset_video', { method: 'POST' })
        .then(() => {
            document.getElementById('videoStream').src = '';
            document.getElementById('toggleButton').disabled = true;

            // Reset sliders to default values
            for (let key in defaultZone) {
                document.getElementById(key).value = defaultZone[key];
            }
            updateZone();
        });
});

// Initialize zone on page load
updateZone();