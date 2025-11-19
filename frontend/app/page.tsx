export default function Home() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Navigation Bar */}
      <nav className="w-full bg-gray-800 text-white p-4">
        <h1 className="text-xl font-semibold">Robot Control Dashboard</h1>
      </nav>

      {/* Main Content Area */}
      <div className="flex-1 flex gap-4 p-4">
        {/* Left Side Boxes */}
        <div className="flex flex-col gap-4 flex-1 max-h-[600px]">
          <div className="bg-gray-200 rounded-lg p-4 flex-1 flex items-center justify-center">
            <span className="text-gray-500">Box 1</span>
          </div>
          <div className="bg-gray-200 rounded-lg p-4 flex-1 flex items-center justify-center">
            <span className="text-gray-500">Box 2</span>
          </div>
        </div>

        {/* Center Camera/Video Feed */}
        <div className="flex items-center justify-center">
          <div className="bg-black aspect-square w-[700px] h-[600px] rounded-lg flex items-center justify-center">
            <span className="text-white text-lg">Camera Feed</span>
          </div>
        </div>

        {/* Right Side Boxes */}
        <div className="flex flex-col gap-4 flex-1 max-h-[600px]">
          <div className="bg-gray-200 rounded-lg p-4 flex-1 flex items-center justify-center">
            <span className="text-gray-500">Box 3</span>
          </div>
          <div className="bg-gray-200 rounded-lg p-4 flex-1 flex items-center justify-center">
            <span className="text-gray-500">Box 4</span>
          </div>
        </div>
      </div>
    </div>
  );
}
