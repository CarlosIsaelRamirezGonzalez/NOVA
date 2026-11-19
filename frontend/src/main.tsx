/** Punto de entrada de la aplicación web. */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AccessGate } from './components/AccessGate'

// Monta la aplicación en el nodo raíz de index.html; en la web, después de la contraseña.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AccessGate>
      <App />
    </AccessGate>
  </StrictMode>,
)
