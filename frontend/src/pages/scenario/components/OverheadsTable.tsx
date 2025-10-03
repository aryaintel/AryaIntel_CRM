import { ScenarioDetail, ScenarioOverhead } from "../../../types/scenario";
import { SectionHeader } from "../../../components/ui";
import { fmt, fmtPct } from "../../../utils/format";

export default function OverheadsTable({
  data,
  onNewOvh,
  onEditOvh,
  onDeleteOvh,
}: {
  data: ScenarioDetail;
  onNewOvh: () => void;
  onEditOvh: (o: ScenarioOverhead) => void;
  onDeleteOvh: (o: ScenarioOverhead) => void;
}) {
  return (
    <>
      <SectionHeader
        title="Overheads"
        right={
          <button
            onClick={onNewOvh}
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500"
          >
            + Add Overhead
          </button>
        }
      />
      {data.overheads.length === 0 ? (
        <div className="text-sm text-gray-500 mb-4">No overheads yet.</div>
      ) : (
        <div className="overflow-x-auto mb-6">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left border-b">
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Type</th>
                <th className="py-2 pr-4">Amount</th>
                <th className="py-2 pr-4 w-56 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.overheads.map((o) => (
                <tr key={o.id} className="border-b last:border-0">
                  <td className="py-2 pr-4 font-medium">{o.name}</td>
                  <td className="py-2 pr-4">{o.type === "fixed" ? "Fixed" : "% of Revenue"}</td>
                  <td className="py-2 pr-4">{o.type === "%_revenue" ? `${fmtPct(o.amount)}%` : fmt(o.amount)}</td>
                  <td className="py-2 pr-4 text-right">
                    <button onClick={() => onEditOvh(o)} className="px-2 py-1 rounded border mr-2 hover:bg-gray-50">
                      Edit
                    </button>
                    <button onClick={() => onDeleteOvh(o)} className="px-2 py-1 rounded border hover:bg-gray-50">
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
