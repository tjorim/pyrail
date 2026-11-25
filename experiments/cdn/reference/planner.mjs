// Runs journey searches in the reference planner, @irail/planner, for compare_journeys.py.
// Input (stdin): a JSON array of {from, to, time (ISO 8601), arriveBy}.
// Output (stdout): one JSON array per query of {departure, arrival, transfers, vehicles} (ISO times, UTC).
// Setup: npm install --prefix experiments/cdn/reference   (Node 22.12 or newer)
import { createPlanner } from "@irail/planner";

const planner = createPlanner({ dataUrl: "https://irail.github.io/iRail-cdn/manifest.jsonld" });
await planner.init();
const queries = JSON.parse(await new Response(process.stdin).text());
const answers = [];
for (const query of queries) {
  try {
    const journeys = await planner.connections({
      from: query.from,
      to: query.to,
      time: new Date(query.time),
      arriveBy: query.arriveBy,
    });
    answers.push(
      journeys.map((journey) => ({
        departure: journey.departure.toISOString(),
        arrival: journey.arrival.toISOString(),
        transfers: journey.transfers,
        canceled: journey.canceled,
        vehicles: journey.legs.map((leg) => leg.vehicle?.name ?? leg.type).join(" > "),
      })),
    );
  } catch (error) {
    answers.push({ error: `${error.name}: ${error.message}` });
  }
}
process.stdout.write(JSON.stringify(answers));
