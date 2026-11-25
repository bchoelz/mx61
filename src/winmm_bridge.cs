using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace Mx61Midi
{
    public static class Bridge
    {
        private const int CALLBACK_FUNCTION = 0x00030000;
        private const int MIM_DATA = 0x3C3;
        private const int MIM_LONGDATA = 0x3C4;
        private const int MMSYSERR_NOERROR = 0;

        public delegate void MidiInProc(IntPtr hMidiIn, int wMsg, IntPtr dwInstance, IntPtr dwParam1, IntPtr dwParam2);

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
        public struct MIDIOUTCAPS
        {
            public ushort wMid;
            public ushort wPid;
            public uint vDriverVersion;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
            public string szPname;
            public ushort wTechnology;
            public ushort wVoices;
            public ushort wNotes;
            public ushort wChannelMask;
            public uint dwSupport;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
        public struct MIDIINCAPS
        {
            public ushort wMid;
            public ushort wPid;
            public uint vDriverVersion;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
            public string szPname;
            public uint dwSupport;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct MIDIHDR
        {
            public IntPtr lpData;
            public uint dwBufferLength;
            public uint dwBytesRecorded;
            public IntPtr dwUser;
            public uint dwFlags;
            public IntPtr lpNext;
            public IntPtr reserved;
            public uint dwOffset;
            [MarshalAs(UnmanagedType.ByValArray, SizeConst = 8)]
            public IntPtr[] dwReserved;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
        public struct WAVEINCAPS
        {
            public ushort wMid;
            public ushort wPid;
            public uint vDriverVersion;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
            public string szPname;
            public uint dwFormats;
            public ushort wChannels;
            public ushort wReserved1;
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
        public struct WAVEOUTCAPS
        {
            public ushort wMid;
            public ushort wPid;
            public uint vDriverVersion;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
            public string szPname;
            public uint dwFormats;
            public ushort wChannels;
            public ushort wReserved1;
            public uint dwSupport;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct WAVEFORMATEX
        {
            public ushort wFormatTag;
            public ushort nChannels;
            public uint nSamplesPerSec;
            public uint nAvgBytesPerSec;
            public ushort nBlockAlign;
            public ushort wBitsPerSample;
            public ushort cbSize;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct WAVEHDR
        {
            public IntPtr lpData;
            public uint dwBufferLength;
            public uint dwBytesRecorded;
            public IntPtr dwUser;
            public uint dwFlags;
            public uint dwLoops;
            public IntPtr lpNext;
            public IntPtr reserved;
        }

        [DllImport("winmm.dll", CharSet = CharSet.Auto)]
        private static extern uint midiOutGetNumDevs();

        [DllImport("winmm.dll", CharSet = CharSet.Auto)]
        private static extern int midiOutGetDevCaps(IntPtr uDeviceID, out MIDIOUTCAPS lpMidiOutCaps, uint cbMidiOutCaps);

        [DllImport("winmm.dll", CharSet = CharSet.Auto)]
        private static extern uint midiInGetNumDevs();

        [DllImport("winmm.dll", CharSet = CharSet.Auto)]
        private static extern int midiInGetDevCaps(IntPtr uDeviceID, out MIDIINCAPS lpMidiInCaps, uint cbMidiInCaps);

        [DllImport("winmm.dll")]
        private static extern int midiOutOpen(out IntPtr lphMidiOut, uint uDeviceID, IntPtr dwCallback, IntPtr dwInstance, int dwFlags);

        [DllImport("winmm.dll")]
        private static extern int midiOutClose(IntPtr hMidiOut);

        [DllImport("winmm.dll")]
        private static extern int midiOutReset(IntPtr hMidiOut);

        [DllImport("winmm.dll")]
        private static extern int midiOutShortMsg(IntPtr hMidiOut, uint dwMsg);

        [DllImport("winmm.dll")]
        private static extern int midiOutPrepareHeader(IntPtr hMidiOut, IntPtr lpMidiOutHdr, uint uSize);

        [DllImport("winmm.dll")]
        private static extern int midiOutUnprepareHeader(IntPtr hMidiOut, IntPtr lpMidiOutHdr, uint uSize);

        [DllImport("winmm.dll")]
        private static extern int midiOutLongMsg(IntPtr hMidiOut, IntPtr lpMidiOutHdr, uint uSize);

        [DllImport("winmm.dll")]
        private static extern int midiInOpen(out IntPtr lphMidiIn, uint uDeviceID, MidiInProc dwCallback, IntPtr dwInstance, int dwFlags);

        [DllImport("winmm.dll")]
        private static extern int midiInClose(IntPtr hMidiIn);

        [DllImport("winmm.dll")]
        private static extern int midiInStart(IntPtr hMidiIn);

        [DllImport("winmm.dll")]
        private static extern int midiInStop(IntPtr hMidiIn);

        [DllImport("winmm.dll")]
        private static extern int midiInReset(IntPtr hMidiIn);

        [DllImport("winmm.dll")]
        private static extern int midiInPrepareHeader(IntPtr hMidiIn, IntPtr lpMidiInHdr, uint uSize);

        [DllImport("winmm.dll")]
        private static extern int midiInUnprepareHeader(IntPtr hMidiIn, IntPtr lpMidiInHdr, uint uSize);

        [DllImport("winmm.dll")]
        private static extern int midiInAddBuffer(IntPtr hMidiIn, IntPtr lpMidiInHdr, uint uSize);

        [DllImport("winmm.dll", CharSet = CharSet.Auto)]
        private static extern uint waveInGetNumDevs();

        [DllImport("winmm.dll", CharSet = CharSet.Auto)]
        private static extern int waveInGetDevCaps(IntPtr uDeviceID, out WAVEINCAPS pwic, uint cbwic);

        [DllImport("winmm.dll")]
        private static extern int waveInOpen(out IntPtr phwi, uint uDeviceID, ref WAVEFORMATEX pwfx, IntPtr dwCallback, IntPtr dwInstance, int fdwOpen);

        [DllImport("winmm.dll")]
        private static extern int waveInPrepareHeader(IntPtr hwi, IntPtr pwh, uint cbwh);

        [DllImport("winmm.dll")]
        private static extern int waveInUnprepareHeader(IntPtr hwi, IntPtr pwh, uint cbwh);

        [DllImport("winmm.dll")]
        private static extern int waveInAddBuffer(IntPtr hwi, IntPtr pwh, uint cbwh);

        [DllImport("winmm.dll")]
        private static extern int waveInStart(IntPtr hwi);

        [DllImport("winmm.dll")]
        private static extern int waveInStop(IntPtr hwi);

        [DllImport("winmm.dll")]
        private static extern int waveInReset(IntPtr hwi);

        [DllImport("winmm.dll")]
        private static extern int waveInClose(IntPtr hwi);

        [DllImport("winmm.dll", CharSet = CharSet.Auto)]
        private static extern uint waveOutGetNumDevs();

        [DllImport("winmm.dll", CharSet = CharSet.Auto)]
        private static extern int waveOutGetDevCaps(IntPtr uDeviceID, out WAVEOUTCAPS pwoc, uint cbwoc);

        [DllImport("winmm.dll")]
        private static extern int waveOutOpen(out IntPtr phwo, uint uDeviceID, ref WAVEFORMATEX pwfx, IntPtr dwCallback, IntPtr dwInstance, int fdwOpen);

        [DllImport("winmm.dll")]
        private static extern int waveOutPrepareHeader(IntPtr hwo, IntPtr pwh, uint cbwh);

        [DllImport("winmm.dll")]
        private static extern int waveOutUnprepareHeader(IntPtr hwo, IntPtr pwh, uint cbwh);

        [DllImport("winmm.dll")]
        private static extern int waveOutWrite(IntPtr hwo, IntPtr pwh, uint cbwh);

        [DllImport("winmm.dll")]
        private static extern int waveOutReset(IntPtr hwo);

        [DllImport("winmm.dll")]
        private static extern int waveOutClose(IntPtr hwo);

        private static readonly object _sync = new object();
        private static List<string> _receivedEvents = new List<string>();
        private static bool _shuttingDown = false;
        private static MidiInProc _callbackDelegate;

        private static void OnMidiIn(IntPtr hMidiIn, int wMsg, IntPtr dwInstance, IntPtr dwParam1, IntPtr dwParam2)
        {
            if (wMsg == MIM_DATA)
            {
                uint raw = (uint)dwParam1.ToInt64();
                byte status = (byte)(raw & 0xFF);
                if (status == 0xF8 || status == 0xFE)
                {
                    return; // Ignore Timing Clock (F8) and Active Sensing (FE)
                }
                byte data1 = (byte)((raw >> 8) & 0xFF);
                byte data2 = (byte)((raw >> 16) & 0xFF);
                lock (_sync)
                {
                    _receivedEvents.Add(string.Format("SHORT:{0:X2}{1:X2}{2:X2}", status, data1, data2));
                }
            }
            else if (wMsg == MIM_LONGDATA)
            {
                MIDIHDR hdr = (MIDIHDR)Marshal.PtrToStructure(dwParam1, typeof(MIDIHDR));
                if (hdr.dwBytesRecorded > 0 && hdr.lpData != IntPtr.Zero)
                {
                    byte[] bytes = new byte[hdr.dwBytesRecorded];
                    Marshal.Copy(hdr.lpData, bytes, 0, (int)hdr.dwBytesRecorded);
                    StringBuilder sb = new StringBuilder("SYSEX:");
                    for (int i = 0; i < bytes.Length; i++)
                    {
                        sb.AppendFormat("{0:X2}", bytes[i]);
                    }
                    lock (_sync)
                    {
                        _receivedEvents.Add(sb.ToString());
                    }
                }
                if (!_shuttingDown && hMidiIn != IntPtr.Zero && dwParam1 != IntPtr.Zero)
                {
                    hdr.dwBytesRecorded = 0;
                    Marshal.StructureToPtr(hdr, dwParam1, false);
                    midiInAddBuffer(hMidiIn, dwParam1, (uint)Marshal.SizeOf(typeof(MIDIHDR)));
                }
            }
        }

        public static int FindMxOutPort()
        {
            uint count = midiOutGetNumDevs();
            // Priority 1: Yamaha MX49/MX61 Port 1 (Main Synth Engine & SysEx Port)
            string[] port1Keywords = new string[] { "MX49/MX61-1", "MX61-1", "MX49-1", "YAMAHA MX" };
            for (int k = 0; k < port1Keywords.Length; k++)
            {
                for (uint i = 0; i < count; i++)
                {
                    MIDIOUTCAPS caps;
                    if (midiOutGetDevCaps((IntPtr)i, out caps, (uint)Marshal.SizeOf(typeof(MIDIOUTCAPS))) == MMSYSERR_NOERROR)
                    {
                        string up = (caps.szPname ?? "").ToUpperInvariant();
                        if (up.Contains(port1Keywords[k]))
                        {
                            return (int)i;
                        }
                    }
                }
            }
            // Priority 2: Any MX49/MX61/Yamaha port (excluding DAW remote port -2..-5 if Port 1 exists)
            string[] fallbackKeywords = new string[] { "MX49/MX61", "MX61", "MX49", "YAMAHA", "STEINBERG" };
            for (int k = 0; k < fallbackKeywords.Length; k++)
            {
                for (uint i = 0; i < count; i++)
                {
                    MIDIOUTCAPS caps;
                    if (midiOutGetDevCaps((IntPtr)i, out caps, (uint)Marshal.SizeOf(typeof(MIDIOUTCAPS))) == MMSYSERR_NOERROR)
                    {
                        string up = (caps.szPname ?? "").ToUpperInvariant();
                        if (up.Contains(fallbackKeywords[k]) && !up.Contains("-2") && !up.Contains("-3") && !up.Contains("-4") && !up.Contains("-5"))
                        {
                            return (int)i;
                        }
                    }
                }
            }
            // Priority 3: First non-synth hardware port
            for (uint i = 0; i < count; i++)
            {
                MIDIOUTCAPS caps;
                if (midiOutGetDevCaps((IntPtr)i, out caps, (uint)Marshal.SizeOf(typeof(MIDIOUTCAPS))) == MMSYSERR_NOERROR)
                {
                    string up = (caps.szPname ?? "").ToUpperInvariant();
                    if (!up.Contains("GS WAVETABLE") && !up.Contains("SYNTH"))
                    {
                        return (int)i;
                    }
                }
            }
            return count > 0 ? 0 : -1;
        }

        public static int FindMxInPort()
        {
            uint count = midiInGetNumDevs();
            string[] port1Keywords = new string[] { "MX49/MX61-1", "MX61-1", "MX49-1", "YAMAHA MX" };
            for (int k = 0; k < port1Keywords.Length; k++)
            {
                for (uint i = 0; i < count; i++)
                {
                    MIDIINCAPS caps;
                    if (midiInGetDevCaps((IntPtr)i, out caps, (uint)Marshal.SizeOf(typeof(MIDIINCAPS))) == MMSYSERR_NOERROR)
                    {
                        string up = (caps.szPname ?? "").ToUpperInvariant();
                        if (up.Contains(port1Keywords[k]))
                        {
                            return (int)i;
                        }
                    }
                }
            }
            string[] fallbackKeywords = new string[] { "MX49/MX61", "MX61", "MX49", "YAMAHA", "STEINBERG" };
            for (int k = 0; k < fallbackKeywords.Length; k++)
            {
                for (uint i = 0; i < count; i++)
                {
                    MIDIINCAPS caps;
                    if (midiInGetDevCaps((IntPtr)i, out caps, (uint)Marshal.SizeOf(typeof(MIDIINCAPS))) == MMSYSERR_NOERROR)
                    {
                        string up = (caps.szPname ?? "").ToUpperInvariant();
                        if (up.Contains(fallbackKeywords[k]) && !up.Contains("-2") && !up.Contains("-3") && !up.Contains("-4") && !up.Contains("-5"))
                        {
                            return (int)i;
                        }
                    }
                }
            }
            return count > 0 ? 0 : -1;
        }

        public static int FindAudioInPort()
        {
            uint count = waveInGetNumDevs();
            // Priority 1: Built-in Yamaha MX49/MX61 USB Audio Interface (Steinberg / Yamaha USB Audio Driver)
            // Priority 2: Fallback external audio interface (M-Track / USB Audio)
            string[] keywords = new string[] { "MX49/MX61", "MX61", "MX49", "YAMAHA", "STEINBERG", "M-TRACK", "M-AUDIO", "USB AUDIO", "LINE" };
            for (int k = 0; k < keywords.Length; k++)
            {
                for (uint i = 0; i < count; i++)
                {
                    WAVEINCAPS caps;
                    if (waveInGetDevCaps((IntPtr)i, out caps, (uint)Marshal.SizeOf(typeof(WAVEINCAPS))) == MMSYSERR_NOERROR)
                    {
                        string up = (caps.szPname ?? "").ToUpperInvariant();
                        if (up.Contains(keywords[k]))
                        {
                            return (int)i;
                        }
                    }
                }
            }
            return count > 0 ? 0 : -1;
        }

        public static int FindAudioOutPort()
        {
            uint count = waveOutGetNumDevs();
            string[] keywords = new string[] { "MX49/MX61", "MX61", "MX49", "YAMAHA", "STEINBERG", "M-TRACK", "M-AUDIO", "USB AUDIO", "HEADPHONE", "SPEAKER" };
            for (int k = 0; k < keywords.Length; k++)
            {
                for (uint i = 0; i < count; i++)
                {
                    WAVEOUTCAPS caps;
                    if (waveOutGetDevCaps((IntPtr)i, out caps, (uint)Marshal.SizeOf(typeof(WAVEOUTCAPS))) == MMSYSERR_NOERROR)
                    {
                        string up = (caps.szPname ?? "").ToUpperInvariant();
                        if (up.Contains(keywords[k]))
                        {
                            return (int)i;
                        }
                    }
                }
            }
            return count > 0 ? 0 : -1;
        }

        public static void ListDevices()
        {
            uint outCount = midiOutGetNumDevs();
            Console.WriteLine("MIDI_OUT_COUNT:" + outCount);
            for (uint i = 0; i < outCount; i++)
            {
                MIDIOUTCAPS caps;
                if (midiOutGetDevCaps((IntPtr)i, out caps, (uint)Marshal.SizeOf(typeof(MIDIOUTCAPS))) == MMSYSERR_NOERROR)
                {
                    Console.WriteLine(string.Format("MIDI_OUT:{0}:{1}:MID={2:X4}:PID={3:X4}", i, caps.szPname, caps.wMid, caps.wPid));
                }
            }

            uint inCount = midiInGetNumDevs();
            Console.WriteLine("MIDI_IN_COUNT:" + inCount);
            for (uint i = 0; i < inCount; i++)
            {
                MIDIINCAPS caps;
                if (midiInGetDevCaps((IntPtr)i, out caps, (uint)Marshal.SizeOf(typeof(MIDIINCAPS))) == MMSYSERR_NOERROR)
                {
                    Console.WriteLine(string.Format("MIDI_IN:{0}:{1}:MID={2:X4}:PID={3:X4}", i, caps.szPname, caps.wMid, caps.wPid));
                }
            }

            uint waveInCount = waveInGetNumDevs();
            Console.WriteLine("AUDIO_IN_COUNT:" + waveInCount);
            for (uint i = 0; i < waveInCount; i++)
            {
                WAVEINCAPS wcaps;
                if (waveInGetDevCaps((IntPtr)i, out wcaps, (uint)Marshal.SizeOf(typeof(WAVEINCAPS))) == MMSYSERR_NOERROR)
                {
                    Console.WriteLine(string.Format("AUDIO_IN:{0}:{1}:CH={2}:MID={3:X4}:PID={4:X4}", i, wcaps.szPname, wcaps.wChannels, wcaps.wMid, wcaps.wPid));
                }
            }

            uint waveOutCount = waveOutGetNumDevs();
            Console.WriteLine("AUDIO_OUT_COUNT:" + waveOutCount);
            for (uint i = 0; i < waveOutCount; i++)
            {
                WAVEOUTCAPS ocaps;
                if (waveOutGetDevCaps((IntPtr)i, out ocaps, (uint)Marshal.SizeOf(typeof(WAVEOUTCAPS))) == MMSYSERR_NOERROR)
                {
                    Console.WriteLine(string.Format("AUDIO_OUT:{0}:{1}:CH={2}:MID={3:X4}:PID={4:X4}", i, ocaps.szPname, ocaps.wChannels, ocaps.wMid, ocaps.wPid));
                }
            }
        }

        private static byte[] HexToBytes(string hex)
        {
            string clean = hex.Replace(" ", "").Replace("-", "").Replace(":", "").Trim();
            byte[] bytes = new byte[clean.Length / 2];
            for (int i = 0; i < bytes.Length; i++)
            {
                bytes[i] = byte.Parse(clean.Substring(i * 2, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
            }
            return bytes;
        }

        private static void SendPacketOnHandle(IntPtr hOut, byte[] data, int postDelayMs)
        {
            if (data == null || data.Length == 0)
            {
                return;
            }
            if (data[0] == 0xF0)
            {
                IntPtr unmanagedData = Marshal.AllocHGlobal(data.Length);
                IntPtr unmanagedHdr = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(MIDIHDR)));
                try
                {
                    Marshal.Copy(data, 0, unmanagedData, data.Length);
                    MIDIHDR hdr = new MIDIHDR();
                    hdr.lpData = unmanagedData;
                    hdr.dwBufferLength = (uint)data.Length;
                    hdr.dwBytesRecorded = (uint)data.Length;
                    hdr.dwFlags = 0;
                    Marshal.StructureToPtr(hdr, unmanagedHdr, false);

                    uint hdrSize = (uint)Marshal.SizeOf(typeof(MIDIHDR));
                    int prep = midiOutPrepareHeader(hOut, unmanagedHdr, hdrSize);
                    if (prep != MMSYSERR_NOERROR)
                    {
                        throw new Exception("midiOutPrepareHeader error: " + prep);
                    }
                    int send = midiOutLongMsg(hOut, unmanagedHdr, hdrSize);
                    if (send != MMSYSERR_NOERROR)
                    {
                        midiOutUnprepareHeader(hOut, unmanagedHdr, hdrSize);
                        throw new Exception("midiOutLongMsg error: " + send);
                    }

                    int waitTicks = 0;
                    while (waitTicks < 200)
                    {
                        MIDIHDR cur = (MIDIHDR)Marshal.PtrToStructure(unmanagedHdr, typeof(MIDIHDR));
                        if ((cur.dwFlags & 1) != 0)
                        {
                            break;
                        }
                        Thread.Sleep(5);
                        waitTicks++;
                    }
                    midiOutUnprepareHeader(hOut, unmanagedHdr, hdrSize);
                }
                finally
                {
                    Marshal.FreeHGlobal(unmanagedHdr);
                    Marshal.FreeHGlobal(unmanagedData);
                }
            }
            else if (data.Length <= 3)
            {
                uint msg = data[0];
                if (data.Length > 1) msg |= ((uint)data[1] << 8);
                if (data.Length > 2) msg |= ((uint)data[2] << 16);
                int rc = midiOutShortMsg(hOut, msg);
                if (rc != MMSYSERR_NOERROR)
                {
                    throw new Exception("midiOutShortMsg error: " + rc);
                }
            }
            if (postDelayMs > 0)
            {
                Thread.Sleep(postDelayMs);
            }
        }

        public static void ExecuteTransaction(string[] hexPackets, int interPacketDelayMs, int listenWindowMs)
        {
            int outPort = FindMxOutPort();
            int inPort = FindMxInPort();
            if (outPort < 0)
            {
                Console.WriteLine("ERROR:NO_MIDI_OUT_PORT");
                return;
            }

            IntPtr hOut = IntPtr.Zero;
            IntPtr hIn = IntPtr.Zero;
            const int NUM_IN_BUFFERS = 64;
            const int IN_BUFFER_SIZE = 8192;
            IntPtr[] inDataPtrs = new IntPtr[NUM_IN_BUFFERS];
            IntPtr[] inHdrPtrs = new IntPtr[NUM_IN_BUFFERS];
            uint hdrSize = (uint)Marshal.SizeOf(typeof(MIDIHDR));

            lock (_sync)
            {
                _receivedEvents.Clear();
                _shuttingDown = false;
            }

            try
            {
                int rcOut = midiOutOpen(out hOut, (uint)outPort, IntPtr.Zero, IntPtr.Zero, 0);
                if (rcOut != MMSYSERR_NOERROR)
                {
                    Console.WriteLine("ERROR:MIDI_OUT_OPEN_FAILED:" + rcOut);
                    return;
                }

                if (inPort >= 0 && listenWindowMs > 0)
                {
                    _callbackDelegate = new MidiInProc(OnMidiIn);
                    int rcIn = midiInOpen(out hIn, (uint)inPort, _callbackDelegate, IntPtr.Zero, CALLBACK_FUNCTION);
                    if (rcIn == MMSYSERR_NOERROR)
                    {
                        for (int b = 0; b < NUM_IN_BUFFERS; b++)
                        {
                            inDataPtrs[b] = Marshal.AllocHGlobal(IN_BUFFER_SIZE);
                            inHdrPtrs[b] = Marshal.AllocHGlobal((int)hdrSize);
                            MIDIHDR hdr = new MIDIHDR();
                            hdr.lpData = inDataPtrs[b];
                            hdr.dwBufferLength = IN_BUFFER_SIZE;
                            hdr.dwBytesRecorded = 0;
                            hdr.dwFlags = 0;
                            Marshal.StructureToPtr(hdr, inHdrPtrs[b], false);
                            midiInPrepareHeader(hIn, inHdrPtrs[b], hdrSize);
                            midiInAddBuffer(hIn, inHdrPtrs[b], hdrSize);
                        }
                        midiInStart(hIn);
                    }
                }

                if (hexPackets != null)
                {
                    for (int i = 0; i < hexPackets.Length; i++)
                    {
                        string pkt = hexPackets[i];
                        if (string.IsNullOrWhiteSpace(pkt)) continue;
                        if (pkt.StartsWith("SLEEP:", StringComparison.OrdinalIgnoreCase))
                        {
                            int sleepMs = int.Parse(pkt.Substring(6).Trim(), CultureInfo.InvariantCulture);
                            if (sleepMs > 0) Thread.Sleep(sleepMs);
                            continue;
                        }
                        byte[] bytes = HexToBytes(pkt);
                        SendPacketOnHandle(hOut, bytes, interPacketDelayMs);
                    }
                }

                if (listenWindowMs > 0)
                {
                    Thread.Sleep(listenWindowMs);
                }
            }
            finally
            {
                _shuttingDown = true;
                if (hIn != IntPtr.Zero)
                {
                    midiInStop(hIn);
                    midiInReset(hIn);
                    for (int b = 0; b < NUM_IN_BUFFERS; b++)
                    {
                        if (inHdrPtrs[b] != IntPtr.Zero)
                        {
                            midiInUnprepareHeader(hIn, inHdrPtrs[b], hdrSize);
                            Marshal.FreeHGlobal(inHdrPtrs[b]);
                        }
                        if (inDataPtrs[b] != IntPtr.Zero)
                        {
                            Marshal.FreeHGlobal(inDataPtrs[b]);
                        }
                    }
                    midiInClose(hIn);
                }
                if (hOut != IntPtr.Zero)
                {
                    midiOutReset(hOut);
                    midiOutClose(hOut);
                }
            }

            Console.WriteLine("PORT_OUT:" + outPort + ":PORT_IN:" + inPort);
            lock (_sync)
            {
                Console.WriteLine("RX_COUNT:" + _receivedEvents.Count);
                for (int i = 0; i < _receivedEvents.Count; i++)
                {
                    Console.WriteLine("RX:" + _receivedEvents[i]);
                }
            }
        }

        private static void WriteWavFile(string wavPath, byte[] pcmData, int sampleRate, short channels, short bitsPerSample)
        {
            using (FileStream fs = new FileStream(wavPath, FileMode.Create, FileAccess.Write))
            using (BinaryWriter bw = new BinaryWriter(fs))
            {
                int byteRate = sampleRate * channels * (bitsPerSample / 8);
                short blockAlign = (short)(channels * (bitsPerSample / 8));
                bw.Write(Encoding.ASCII.GetBytes("RIFF"));
                bw.Write(36 + pcmData.Length);
                bw.Write(Encoding.ASCII.GetBytes("WAVE"));
                bw.Write(Encoding.ASCII.GetBytes("fmt "));
                bw.Write(16);
                bw.Write((short)1); // PCM
                bw.Write(channels);
                bw.Write(sampleRate);
                bw.Write(byteRate);
                bw.Write(blockAlign);
                bw.Write(bitsPerSample);
                bw.Write(Encoding.ASCII.GetBytes("data"));
                bw.Write(pcmData.Length);
                bw.Write(pcmData);
            }
        }

        public static void RecordAudioAndPlayMidi(string wavPath, int durationMs, int sampleRate, string[] hexPackets, int interPacketDelayMs)
        {
            int audioPort = FindAudioInPort();
            if (audioPort < 0)
            {
                Console.WriteLine("ERROR:NO_AUDIO_IN_PORT");
                return;
            }
            int midiOutPort = FindMxOutPort();

            short channels = 2;
            short bitsPerSample = 16;
            int blockAlign = channels * (bitsPerSample / 8);
            int byteRate = sampleRate * blockAlign;
            int totalBytes = (int)(((long)durationMs * byteRate) / 1000L);
            if (totalBytes % blockAlign != 0)
            {
                totalBytes += blockAlign - (totalBytes % blockAlign);
            }

            WAVEFORMATEX fmt = new WAVEFORMATEX();
            fmt.wFormatTag = 1;
            fmt.nChannels = (ushort)channels;
            fmt.nSamplesPerSec = (uint)sampleRate;
            fmt.nAvgBytesPerSec = (uint)byteRate;
            fmt.nBlockAlign = (ushort)blockAlign;
            fmt.wBitsPerSample = (ushort)bitsPerSample;
            fmt.cbSize = 0;

            IntPtr hWaveIn = IntPtr.Zero;
            IntPtr hMidiOut = IntPtr.Zero;
            IntPtr unmanagedAudioBuf = Marshal.AllocHGlobal(totalBytes);
            IntPtr unmanagedWaveHdr = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(WAVEHDR)));
            uint waveHdrSize = (uint)Marshal.SizeOf(typeof(WAVEHDR));
            bool headerPrepared = false;

            try
            {
                WAVEINCAPS wcaps;
                string devName = "UnknownAudioIn";
                if (waveInGetDevCaps((IntPtr)audioPort, out wcaps, (uint)Marshal.SizeOf(typeof(WAVEINCAPS))) == MMSYSERR_NOERROR)
                {
                    devName = wcaps.szPname;
                }

                int rcW = waveInOpen(out hWaveIn, (uint)audioPort, ref fmt, IntPtr.Zero, IntPtr.Zero, 0);
                if (rcW != MMSYSERR_NOERROR)
                {
                    Console.WriteLine("ERROR:WAVE_IN_OPEN_FAILED:" + rcW);
                    return;
                }

                WAVEHDR whdr = new WAVEHDR();
                whdr.lpData = unmanagedAudioBuf;
                whdr.dwBufferLength = (uint)totalBytes;
                whdr.dwBytesRecorded = 0;
                whdr.dwFlags = 0;
                Marshal.StructureToPtr(whdr, unmanagedWaveHdr, false);

                int rcP = waveInPrepareHeader(hWaveIn, unmanagedWaveHdr, waveHdrSize);
                if (rcP != MMSYSERR_NOERROR)
                {
                    Console.WriteLine("ERROR:WAVE_IN_PREPARE_FAILED:" + rcP);
                    return;
                }
                headerPrepared = true;

                waveInAddBuffer(hWaveIn, unmanagedWaveHdr, waveHdrSize);
                waveInStart(hWaveIn);

                DateTime startTime = DateTime.UtcNow;

                if (midiOutPort >= 0 && hexPackets != null && hexPackets.Length > 0)
                {
                    if (midiOutOpen(out hMidiOut, (uint)midiOutPort, IntPtr.Zero, IntPtr.Zero, 0) == MMSYSERR_NOERROR)
                    {
                        Thread.Sleep(150);
                        for (int i = 0; i < hexPackets.Length; i++)
                        {
                            string pkt = hexPackets[i];
                            if (string.IsNullOrWhiteSpace(pkt)) continue;
                            if (pkt.StartsWith("SLEEP:", StringComparison.OrdinalIgnoreCase))
                            {
                                int sleepMs = int.Parse(pkt.Substring(6).Trim(), CultureInfo.InvariantCulture);
                                if (sleepMs > 0) Thread.Sleep(sleepMs);
                                continue;
                            }
                            byte[] bytes = HexToBytes(pkt);
                            SendPacketOnHandle(hMidiOut, bytes, interPacketDelayMs);
                        }
                    }
                }

                while ((DateTime.UtcNow - startTime).TotalMilliseconds < durationMs + 100)
                {
                    WAVEHDR cur = (WAVEHDR)Marshal.PtrToStructure(unmanagedWaveHdr, typeof(WAVEHDR));
                    if ((cur.dwFlags & 1) != 0)
                    {
                        break;
                    }
                    Thread.Sleep(25);
                }

                waveInStop(hWaveIn);
                waveInReset(hWaveIn);

                WAVEHDR finalHdr = (WAVEHDR)Marshal.PtrToStructure(unmanagedWaveHdr, typeof(WAVEHDR));
                int recordedBytes = (int)finalHdr.dwBytesRecorded;
                if (recordedBytes <= 0)
                {
                    recordedBytes = totalBytes;
                }

                byte[] pcm = new byte[recordedBytes];
                Marshal.Copy(unmanagedAudioBuf, pcm, 0, recordedBytes);
                WriteWavFile(wavPath, pcm, sampleRate, channels, bitsPerSample);

                Console.WriteLine(string.Format("AUDIO_CAPTURED:PORT={0}:NAME={1}:BYTES={2}:PATH={3}", audioPort, devName, recordedBytes, wavPath));
            }
            finally
            {
                if (hMidiOut != IntPtr.Zero)
                {
                    midiOutReset(hMidiOut);
                    midiOutClose(hMidiOut);
                }
                if (hWaveIn != IntPtr.Zero)
                {
                    if (headerPrepared)
                    {
                        waveInUnprepareHeader(hWaveIn, unmanagedWaveHdr, waveHdrSize);
                    }
                    waveInClose(hWaveIn);
                }
                Marshal.FreeHGlobal(unmanagedWaveHdr);
                Marshal.FreeHGlobal(unmanagedAudioBuf);
            }
        }
    }

    public class Program
    {
        public static int Main(string[] args)
        {
            if (args.Length == 0 || args[0] == "list")
            {
                Bridge.ListDevices();
                return 0;
            }
            if (args[0] == "txrx")
            {
                int delayMs = args.Length > 1 ? int.Parse(args[1], CultureInfo.InvariantCulture) : 15;
                int listenMs = args.Length > 2 ? int.Parse(args[2], CultureInfo.InvariantCulture) : 500;
                string[] packets = new string[0];
                if (args.Length > 3 && File.Exists(args[3]))
                {
                    packets = File.ReadAllLines(args[3]);
                }
                Bridge.ExecuteTransaction(packets, delayMs, listenMs);
                return 0;
            }
            if (args[0] == "record")
            {
                if (args.Length < 4)
                {
                    Console.WriteLine("ERROR:USAGE:record <wavPath> <durationMs> <sampleRate> [packetsFile] [interPacketDelayMs]");
                    return 1;
                }
                string wavPath = args[1];
                int durationMs = int.Parse(args[2], CultureInfo.InvariantCulture);
                int sampleRate = int.Parse(args[3], CultureInfo.InvariantCulture);
                string[] packets = new string[0];
                if (args.Length > 4 && File.Exists(args[4]))
                {
                    packets = File.ReadAllLines(args[4]);
                }
                int delayMs = args.Length > 5 ? int.Parse(args[5], CultureInfo.InvariantCulture) : 15;
                Bridge.RecordAudioAndPlayMidi(wavPath, durationMs, sampleRate, packets, delayMs);
                return 0;
            }
            return 1;
        }
    }
}
