import { describe, it, expect } from "vitest";
import cases from "../../../packages/contracts/examples/cases.json";
import { parseContract } from "../src/contracts";
describe("shared server/Web contract corpus", () => {
  for (const c of cases.cases)
    it(c.id, () => {
      if (c.valid)
        expect(parseContract(c.model, c.input)).toEqual(c.normalized);
      else expect(() => parseContract(c.model, c.input)).toThrow();
    });
});
