import { ScenarioDetail, ScenarioProduct } from "../../../types/scenario";
import { SectionHeader } from "../../../components/ui";
import { fmt } from "../../../utils/format";

export default function ProductsTable({
  data,
  onNewProd,
  openMonthsEditor,
  onEditProd,
  onDeleteProd,
}: {
  data: ScenarioDetail;
  onNewProd: () => void;
  openMonthsEditor: (p: ScenarioProduct) => void;
  onEditProd: (p: ScenarioProduct) => void;
  onDeleteProd: (p: ScenarioProduct) => void;
}) {
  return (
    <>
      <SectionHeader
        title="Products"
        right={
          <button
            onClick={onNewProd}
            className="px-3 py-1.5 rounded-md bg-indigo-600 text-white text-sm hover:bg-indigo-500"
          >
            + Add Product
          </button>
        }
      />
      {data.products.length === 0 ? (
        <div className="text-sm text-gray-500 mb-4">No products yet.</div>
      ) : (
        <div className="overflow-x-auto mb-6">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left border-b">
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Price</th>
                <th className="py-2 pr-4">Unit COGS</th>
                <th className="py-2 pr-4">Active</th>
                <th className="py-2 pr-4 w-64 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.products.map((p) => (
                <tr key={p.id} className="border-b last:border-0">
                  <td className="py-2 pr-4 font-medium">{p.name}</td>
                  <td className="py-2 pr-4">{fmt(p.price)}</td>
                  <td className="py-2 pr-4">{fmt(p.unit_cogs)}</td>
                  <td className="py-2 pr-4">{p.is_active ? "Yes" : "No"}</td>
                  <td className="py-2 pr-4 text-right">
                    <button onClick={() => openMonthsEditor(p)} className="px-2 py-1 rounded border mr-2 hover:bg-gray-50">
                      Volumes
                    </button>
                    <button onClick={() => onEditProd(p)} className="px-2 py-1 rounded border mr-2 hover:bg-gray-50">
                      Edit
                    </button>
                    <button onClick={() => onDeleteProd(p)} className="px-2 py-1 rounded border hover:bg-gray-50">
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
