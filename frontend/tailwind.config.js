/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#10151F',
        'ink-mid': '#4B5565',
        'ink-soft': '#8A93A3',
        paper: '#F7F8FA',
        surface: '#FFFFFF',
        hairline: '#E2E5EA',
        recovered: '#1F7A5C',
        'recovered-soft': '#E4F1EB',
        risk: '#B45309',
        'risk-soft': '#FBEEE0',
        lost: '#9F1D35',
        'lost-soft': '#F7E6E9',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['"Newsreader"', 'ui-serif', 'serif'],
      },
    },
  },
  plugins: [],
}
