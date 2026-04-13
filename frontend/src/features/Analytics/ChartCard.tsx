import {
  ResponsiveContainer,
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts';

const PIE_COLOURS = ['#ac3500', '#ffb233', '#6366f1', '#5f5e5e', '#22c55e', '#0ea5e9'];

export function ChartCard({ chart }: { chart: any }) {
  const { title, type, data, xAxisKey = 'name', dataKey = 'value', color = '#ac3500' } = chart;

  const renderChart = () => {
    if (type === 'pie') {
      return (
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie data={data} dataKey={dataKey} nameKey={xAxisKey} cx="50%" cy="50%" outerRadius={90} label={({ name, percent }) => `${name} ${((percent || 0) * 100).toFixed(0)}%`} labelLine={false}>
              {data.map((_: any, i: number) => (
                <Cell key={i} fill={PIE_COLOURS[i % PIE_COLOURS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(v: any) => [v, dataKey]} />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      );
    }
    if (type === 'line') {
      return (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey={xAxisKey} tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      );
    }
    // default: bar
    return (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey={xAxisKey} tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip />
          <Bar dataKey={dataKey} fill={color} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  };

  return (
    <div className="bg-white rounded-2xl border border-outline-variant/20 shadow-sm p-4 space-y-3">
      <p className="text-sm font-headline font-bold text-on-surface">{title}</p>
      {renderChart()}
    </div>
  );
}
