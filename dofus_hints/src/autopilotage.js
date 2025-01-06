//DofusPourLesNoobs.com
//Create travel on each positions
$(".paragraph").each(function() {
	var te = /\[(-?\d+(\.\d+)?),\s*(-?\d+(\.\d+)?)]/g;
	$(this).html($(this).html().replace(te,"<span class=\"fast-travel-coord\" data-travel=\"/travel $1,$3\">$&</span>"));
});
//Clipboard API
document.querySelectorAll(".fast-travel-coord").forEach((item, index) => {
	item.addEventListener("click", async (event) => {
		if (!navigator.clipboard) {
			// Clipboard API not available
			return;
		}
		try {
			await navigator.clipboard.writeText(event.target.getAttribute("data-travel"));
			$(".dpln-fast-travel").html("<div class=\"fast-travel-toast\"><img src=\"./src/destination.png\" \/><p>Voyage copié avec succès<\/p><\/div>").fadeIn();
				setTimeout(function(){
					$(".dpln-fast-travel").fadeOut();
				}, 2000);
		} catch (err) {
			console.error("Failed to copy!", err);
		}
	});
});