// MOBILE NAVIGATION
const menuToggle = document.getElementById("menuToggle");
const navLinks = document.getElementById("navLinks");

menuToggle.addEventListener("click", function () {
    navLinks.classList.toggle("active");

    const icon = menuToggle.querySelector("i");

    if (navLinks.classList.contains("active")) {
        icon.classList.replace("fa-bars", "fa-xmark");
    } else {
        icon.classList.replace("fa-xmark", "fa-bars");
    }
});

// MOBILE MENU CLOSE AFTER CLICKING A LINK
document.querySelectorAll(".nav-links a").forEach(function (link) {
    link.addEventListener("click", function () {
        navLinks.classList.remove("active");

        const icon = menuToggle.querySelector("i");
        icon.classList.remove("fa-xmark");
        icon.classList.add("fa-bars");
    });
});

// ANIMATED STATISTICS
const counters = document.querySelectorAll(".counter");

const observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
        if (entry.isIntersecting) {
            const counter = entry.target;
            const target = Number(counter.dataset.target);
            const duration = 1200;
            const startTime = performance.now();

            function updateCounter(currentTime) {
                const progress = Math.min(
                    (currentTime - startTime) / duration,
                    1
                );

                counter.textContent = Math.floor(target * progress);

                if (progress < 1) {
                    requestAnimationFrame(updateCounter);
                }
            }

            requestAnimationFrame(updateCounter);
            observer.unobserve(counter);
        }
    });
}, {
    threshold: 0.5
});

counters.forEach(function (counter) {
    observer.observe(counter);
});

// EVENT CARD ARROWS
const eventGrid = document.getElementById("eventGrid");

document.getElementById("nextEvent").addEventListener("click", function () {
    eventGrid.scrollBy({
        left: 280,
        behavior: "smooth"
    });
});

document.getElementById("prevEvent").addEventListener("click", function () {
    eventGrid.scrollBy({
        left: -280,
        behavior: "smooth"
    });
});


/* CONTACT ENQUIRY FORM */
const contactForm = document.getElementById("contactForm");
const formMessage = document.getElementById("formMessage");

if (contactForm) {
    contactForm.addEventListener("submit", function (event) {
        if (!contactForm.checkValidity()) {
            event.preventDefault();
            contactForm.reportValidity();
            return;
        }

        // Allow the browser to submit the form to Flask.
        // Do not reset the form here.
    });
}

// AUTOMATIC COPYRIGHT YEAR
document.getElementById("year").textContent =
    new Date().getFullYear();