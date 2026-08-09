document.addEventListener("DOMContentLoaded", () => {
    const numbers = document.querySelectorAll('input[type="number"]');
    numbers.forEach((input) => {
        input.addEventListener("input", () => {
            const min = Number(input.min || 0);
            const max = Number(input.max || 100);
            let value = Number(input.value);
            if (value < min) input.value = min;
            if (value > max) input.value = max;
        });
    });
});
