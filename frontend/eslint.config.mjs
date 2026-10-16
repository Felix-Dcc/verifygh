// Next 16 dropped `next lint`; ESLint runs directly with Next's flat config.
// The same rule set as the old .eslintrc.json ("next/core-web-vitals").
import nextVitals from "eslint-config-next/core-web-vitals";

const config = [
  ...nextVitals,
  {
    // New in eslint-plugin-react-hooks 7 (Next 16) and aimed at the React
    // Compiler, which this app does not use. They flag about 40 existing
    // effects and Date.now() reads that behave correctly today; adopting them
    // is a refactor of its own, not part of the framework upgrade.
    rules: {
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/purity": "off",
    },
  },
  {
    ignores: [".next/**", "out/**", "node_modules/**", "next-env.d.ts"],
  },
];

export default config;
