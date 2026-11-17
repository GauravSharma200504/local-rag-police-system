import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import LoginPage from "@/pages/Login";
import { AuthProvider } from "@/contexts/AuthContext";
import { api } from "@/services/api";

describe("Login page", () => {
  it("shows the backend error on invalid credentials", async () => {
    const err = Object.assign(new Error("401"), { isAxiosError: true, response: { status: 401, data: { detail: "Invalid username or password" } } });
    vi.spyOn(api, "post").mockRejectedValueOnce(err);
    render(<MemoryRouter><AuthProvider><LoginPage /></AuthProvider></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrongpass" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Invalid username or password"));
    expect(api.post).toHaveBeenCalledWith("/auth/login", { username: "x", password: "wrongpass" });
  });
});
