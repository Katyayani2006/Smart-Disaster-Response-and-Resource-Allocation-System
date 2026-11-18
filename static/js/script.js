document.addEventListener("DOMContentLoaded", () => {
    const numbers = document.querySelectorAll('input[type="number"]');
    numbers.forEach((input) => {
        input.addEventListener("input", () => {
            if (input.value === "") return;
            const val = Number(input.value);
            if (input.hasAttribute("min") && input.min !== "") {
                const minVal = Number(input.min);
                if (!isNaN(minVal) && val < minVal) {
                    input.value = minVal;
                }
            }
            if (input.hasAttribute("max") && input.max !== "") {
                const maxVal = Number(input.max);
                if (!isNaN(maxVal) && val > maxVal) {
                    input.value = maxVal;
                }
            }
        });
    });
});
