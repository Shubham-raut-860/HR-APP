import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App';
import './index.css';

const THEME_STORAGE_KEY = "vite-ui-theme";
const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
const userTheme = storedTheme === "dark" || storedTheme === "light" || storedTheme === "system"
  ? storedTheme
  : "system";
const resolvedTheme = userTheme === "system"
  ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
  : userTheme;

document.documentElement.classList.remove("light", "dark");
document.documentElement.classList.add(resolvedTheme);
document.documentElement.style.colorScheme = resolvedTheme;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
