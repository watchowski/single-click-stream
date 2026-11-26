// AppLoopback: captures the audio of one process (and its child processes) with the
// Windows process-loopback API (Windows 10 2004+) and writes raw PCM to stdout:
// 48000 Hz, 2 channels, signed 16-bit little-endian.
//   AppLoopback.exe <pid>
// Built automatically by streamer.py with the csc.exe of the .NET Framework.
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

namespace AppLoopback
{
    [ComImport, Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioClient
    {
        [PreserveSig] int Initialize(int shareMode, uint streamFlags, long bufferDuration, long periodicity, IntPtr format, IntPtr sessionGuid);
        [PreserveSig] int GetBufferSize(out uint frames);
        [PreserveSig] int GetStreamLatency(out long latency);
        [PreserveSig] int GetCurrentPadding(out uint padding);
        [PreserveSig] int IsFormatSupported(int shareMode, IntPtr format, IntPtr closest);
        [PreserveSig] int GetMixFormat(out IntPtr format);
        [PreserveSig] int GetDevicePeriod(out long def, out long min);
        [PreserveSig] int Start();
        [PreserveSig] int Stop();
        [PreserveSig] int Reset();
        [PreserveSig] int SetEventHandle(IntPtr handle);
        [PreserveSig] int GetService([MarshalAs(UnmanagedType.LPStruct)] Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object service);
    }

    [ComImport, Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioCaptureClient
    {
        [PreserveSig] int GetBuffer(out IntPtr data, out uint frames, out uint flags, out ulong devicePosition, out ulong qpcPosition);
        [PreserveSig] int ReleaseBuffer(uint frames);
        [PreserveSig] int GetNextPacketSize(out uint frames);
    }

    [ComImport, Guid("72A22D78-CDE4-431D-B8CC-843A71199B6D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IActivateAudioInterfaceAsyncOperation
    {
        [PreserveSig] int GetActivateResult(out int activateResult, [MarshalAs(UnmanagedType.IUnknown)] out object activatedInterface);
    }

    [ComImport, Guid("41D949AB-9862-444A-80F6-C261334DA5EB"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IActivateAudioInterfaceCompletionHandler
    {
        void ActivateCompleted(IActivateAudioInterfaceAsyncOperation operation);
    }

    [ComImport, Guid("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAgileObject { }

    [ClassInterface(ClassInterfaceType.None)]
    class Handler : IActivateAudioInterfaceCompletionHandler, IAgileObject
    {
        public readonly ManualResetEvent Done = new ManualResetEvent(false);
        public int Result = -1;
        public IAudioClient Client;

        public void ActivateCompleted(IActivateAudioInterfaceAsyncOperation operation)
        {
            int hr;
            object iface;
            int r = operation.GetActivateResult(out hr, out iface);
            Result = r != 0 ? r : hr;
            if (Result == 0) Client = (IAudioClient)iface;
            Done.Set();
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    struct ActivationParams
    {
        public int ActivationType;      // 1 = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
        public uint TargetProcessId;
        public int LoopbackMode;        // 0 = include target process tree
    }

    [StructLayout(LayoutKind.Explicit, Size = 24)]
    struct PropVariantBlob
    {
        [FieldOffset(0)] public ushort vt;      // VT_BLOB = 65
        [FieldOffset(8)] public uint cbSize;
        [FieldOffset(16)] public IntPtr pBlobData;
    }

    [StructLayout(LayoutKind.Sequential, Pack = 2)]
    struct WaveFormatEx
    {
        public ushort wFormatTag, nChannels;
        public uint nSamplesPerSec, nAvgBytesPerSec;
        public ushort nBlockAlign, wBitsPerSample, cbSize;
    }

    static class Program
    {
        [DllImport("Mmdevapi.dll", ExactSpelling = true)]
        static extern int ActivateAudioInterfaceAsync([MarshalAs(UnmanagedType.LPWStr)] string path,
            [MarshalAs(UnmanagedType.LPStruct)] Guid riid, IntPtr activationParams,
            IActivateAudioInterfaceCompletionHandler handler, out IActivateAudioInterfaceAsyncOperation operation);

        static int Fail(string msg, int hr)
        {
            Console.Error.WriteLine(msg + " (0x" + hr.ToString("X8") + ")");
            return 1;
        }

        [MTAThread]
        static int Main(string[] args)
        {
            uint pid;
            if (args.Length < 1 || !uint.TryParse(args[0], out pid))
            {
                Console.Error.WriteLine("usage: AppLoopback.exe <pid>");
                return 2;
            }
            const int RATE = 48000, CH = 2, BITS = 16;

            var ap = new ActivationParams { ActivationType = 1, TargetProcessId = pid, LoopbackMode = 0 };
            IntPtr apPtr = Marshal.AllocHGlobal(Marshal.SizeOf(ap));
            Marshal.StructureToPtr(ap, apPtr, false);
            var pv = new PropVariantBlob { vt = 65, cbSize = (uint)Marshal.SizeOf(ap), pBlobData = apPtr };
            IntPtr pvPtr = Marshal.AllocHGlobal(Marshal.SizeOf(pv));
            Marshal.StructureToPtr(pv, pvPtr, false);

            var handler = new Handler();
            IActivateAudioInterfaceAsyncOperation op;
            int hr = ActivateAudioInterfaceAsync("VAD\\Process_Loopback", typeof(IAudioClient).GUID, pvPtr, handler, out op);
            if (hr != 0) return Fail("ActivateAudioInterfaceAsync failed", hr);
            if (!handler.Done.WaitOne(5000)) return Fail("activation timed out", 0);
            if (handler.Result != 0) return Fail("activation failed", handler.Result);
            IAudioClient client = handler.Client;

            var wf = new WaveFormatEx { wFormatTag = 1, nChannels = CH, nSamplesPerSec = RATE, wBitsPerSample = BITS,
                                        nBlockAlign = CH * BITS / 8, nAvgBytesPerSec = RATE * CH * BITS / 8, cbSize = 0 };
            IntPtr wfPtr = Marshal.AllocHGlobal(Marshal.SizeOf(wf));
            Marshal.StructureToPtr(wf, wfPtr, false);
            // LOOPBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY, 100 ms buffer
            hr = client.Initialize(0, 0x00020000u | 0x80000000u | 0x08000000u, 1000000, 0, wfPtr, IntPtr.Zero);
            if (hr != 0) return Fail("IAudioClient.Initialize failed", hr);
            object svc;
            hr = client.GetService(typeof(IAudioCaptureClient).GUID, out svc);
            if (hr != 0) return Fail("GetService failed", hr);
            var capture = (IAudioCaptureClient)svc;
            hr = client.Start();
            if (hr != 0) return Fail("Start failed", hr);
            Console.Error.WriteLine("capturing pid " + pid);

            Stream stdout = Console.OpenStandardOutput();
            byte[] buf = new byte[RATE * CH * 2];
            int block = CH * BITS / 8;
            try
            {
                while (true)
                {
                    Thread.Sleep(10);
                    uint packet;
                    while (capture.GetNextPacketSize(out packet) == 0 && packet > 0)
                    {
                        IntPtr data; uint frames, flags; ulong p1, p2;
                        hr = capture.GetBuffer(out data, out frames, out flags, out p1, out p2);
                        if (hr != 0) return Fail("GetBuffer failed", hr);
                        int bytes = (int)frames * block;
                        if (bytes > buf.Length) buf = new byte[bytes];
                        if ((flags & 2) != 0) Array.Clear(buf, 0, bytes);   // AUDCLNT_BUFFERFLAGS_SILENT
                        else Marshal.Copy(data, buf, 0, bytes);
                        capture.ReleaseBuffer(frames);
                        stdout.Write(buf, 0, bytes);
                    }
                    stdout.Flush();
                }
            }
            catch (IOException)
            {
                return 0;   // the reader closed the pipe
            }
            finally
            {
                client.Stop();
            }
        }
    }
}
