const USD_TO_INR = 83;

export function formatINR(usdPrice: number): string {
  return `₹${Math.round(usdPrice * USD_TO_INR).toLocaleString("en-IN")}`;
}
